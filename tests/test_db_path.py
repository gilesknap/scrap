"""SCRAP_DB_PATH and --db-path: the database apart from the data folder (ADR 46)."""

import os
import subprocess
import sys

import pytest

from scrap.__main__ import main
from scrap.backup import backup, restore
from scrap.store import Store


@pytest.fixture
def apart(tmp_path, monkeypatch):
    """A store whose database is on another "filesystem" (folder) from its files."""
    db = tmp_path / "local" / "scrap.db"
    monkeypatch.setenv("SCRAP_DB_PATH", str(db))
    store = Store(tmp_path / "data")
    store.migrate()
    return store


def test_unset_keeps_the_database_in_the_data_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRAP_DB_PATH", raising=False)
    assert Store(tmp_path).db == tmp_path / "scrap.db"
    monkeypatch.setenv("SCRAP_DB_PATH", "")  # blank counts as unset
    assert Store(tmp_path).db == tmp_path / "scrap.db"


def test_the_setting_moves_the_database_its_lock_and_wal(apart, tmp_path):
    assert apart.db == tmp_path / "local" / "scrap.db"
    assert (tmp_path / "local" / "scrap.db.lock").exists()
    assert not (tmp_path / "data" / "scrap.db").exists()
    assert not (tmp_path / "data" / "scrap.db.lock").exists()
    assert apart.files == tmp_path / "data" / "files"
    assert apart.files.is_dir()


def test_an_explicit_database_beats_the_setting(apart, tmp_path):
    assert Store(tmp_path / "data", tmp_path / "x.db").db == tmp_path / "x.db"


def test_backup_and_restore_keep_the_copy_beside_the_database(
    apart, tmp_path, monkeypatch
):
    with apart.connect() as conn:
        conn.execute("PRAGMA user_version").fetchone()
    bak = tmp_path / "bak"
    backup(apart, bak)
    assert (bak / "scrap.db").is_file() and (bak / "COMPLETE").is_file()
    renames = []
    real = type(apart.db).replace

    def spy(self, target):
        renames.append((self.parent, type(self)(target).parent))
        return real(self, target)

    monkeypatch.setattr(type(apart.db), "replace", spy)
    restore(bak, apart, force=True)
    # The swap never crosses from the data folder to the database's filesystem
    assert renames == [(apart.db.parent, apart.db.parent)]
    assert not (tmp_path / "data" / "scrap.db.restore").exists()
    assert (
        sorted(p.name for p in apart.db.parent.iterdir() if "restore" in p.name) == []
    )


def test_restore_makes_a_missing_database_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRAP_DB_PATH", raising=False)
    source = Store(tmp_path / "a")
    source.migrate()
    backup(source, tmp_path / "bak")
    target = Store(tmp_path / "b", tmp_path / "new" / "scrap.db")
    restore(tmp_path / "bak", target)
    assert target.db.is_file()


def test_cli_db_path_and_data_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SCRAP_DB_PATH", str(tmp_path / "env.db"))
    data = tmp_path / "data"
    db = tmp_path / "flag.db"
    main(["enrich", "--backfill", "--data-dir", str(data), "--db-path", str(db)])
    assert db.is_file() and not (tmp_path / "env.db").exists()
    # --data-dir alone: the database in that folder, as it has always meant
    main(["enrich", "--backfill", "--data-dir", str(data)])
    assert (data / "scrap.db").is_file() and not (tmp_path / "env.db").exists()
    # Neither: the setting
    monkeypatch.setenv("SCRAP_DATA_DIR", str(data))
    main(["enrich", "--backfill"])
    assert (tmp_path / "env.db").is_file()
    capsys.readouterr()


def test_cli_serve_passes_the_database_on(tmp_path, monkeypatch):
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)
    monkeypatch.setenv("SCRAP_DB_PATH", "")
    main(["serve", "--db-path", str(tmp_path / "x.db")])
    assert os.environ["SCRAP_DB_PATH"] == str(tmp_path / "x.db")


def test_cli_backup_uses_the_setting(tmp_path):
    env = {
        **os.environ,
        "SCRAP_DATA_DIR": str(tmp_path / "data"),
        "SCRAP_DB_PATH": str(tmp_path / "d" / "s.db"),
    }
    run = [sys.executable, "-m", "scrap"]
    subprocess.run([*run, "enrich", "--backfill"], env=env, check=True)
    subprocess.run([*run, "backup", str(tmp_path / "bak")], env=env, check=True)
    assert (tmp_path / "bak" / "COMPLETE").is_file()
    assert not (tmp_path / "data" / "scrap.db").exists()


def test_nothing_in_scrap_fights_litestream_for_checkpoints():
    """Litestream controls checkpoints: scrap must never force one (ADR 46)."""
    from pathlib import Path

    import scrap

    root = Path(scrap.__file__).parent
    for path in root.rglob("*.py"):
        text = path.read_text().lower()
        assert "wal_checkpoint" not in text, path
        assert "wal_autocheckpoint" not in text, path
        assert "locking_mode" not in text, path
        assert "pragma synchronous" not in text, path
    # and Litestream's docs ask for a busy timeout, which every connection sets
    db = (root / "store" / "db.py").read_text()
    assert "PRAGMA busy_timeout = 5000" in db
