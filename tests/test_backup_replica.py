"""scrap backup --from-replica: a backup that never opens the live database (ADR 46)."""

import sqlite3
import stat
import time
from contextlib import closing

import pytest

from scrap.__main__ import main
from scrap.backup import restore
from scrap.replica import backup_from_replica, beat, heartbeat_age_hours
from scrap.store import Store, connect

FAKE = """#!/bin/sh
[ "$1" = restore ] || exit 2
out=$3; dir=${4#file://}
[ -e "$dir/FAIL" ] && exit 1
cp "$dir/fake.db" "$out"
"""


@pytest.fixture
def setup(tmp_path, monkeypatch):
    fake = tmp_path / "litestream"
    fake.write_text(FAKE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SCRAP_LITESTREAM_BIN", str(fake))
    monkeypatch.setenv("SCRAP_DB_PATH", str(tmp_path / "live-not-here" / "scrap.db"))
    data = tmp_path / "data"
    replica = data / "litestream"
    replica.mkdir(parents=True)
    source = Store(data, replica / "fake.db")
    source.migrate()
    with closing(connect(source.db)) as conn:
        conn.execute(
            "INSERT INTO page(id, slug, title, created_at, updated_at)"
            " VALUES ('r', 'r', 'replicated', '2026-01-01', '2026-01-01')"
        )
    beat(source.db)
    (data / "files" / "ab").mkdir(parents=True)
    (data / "files" / "ab" / "abcd").write_bytes(b"a file")
    return data, replica


def test_a_backup_from_the_replica_is_complete_and_restorable(
    setup, tmp_path, monkeypatch
):
    data, replica = setup
    dest = tmp_path / "bak"
    backup_from_replica(data, replica, dest)
    assert (dest / "COMPLETE").is_file()
    assert (dest / "files" / "ab" / "abcd").read_bytes() == b"a file"
    assert not (tmp_path / "live-not-here").exists()  # never looked for the live one
    monkeypatch.delenv("SCRAP_DB_PATH")
    target = Store(tmp_path / "new")
    restore(dest, target)
    with closing(sqlite3.connect(target.db)) as conn:
        assert conn.execute("SELECT title FROM page").fetchone()[0] == "replicated"
    assert (target.files / "ab" / "abcd").is_file()


def test_the_cli_does_the_same(setup, tmp_path, monkeypatch):
    data, replica = setup
    monkeypatch.setenv("SCRAP_DATA_DIR", str(data))
    main(["backup", str(tmp_path / "bak"), "--from-replica", str(replica)])
    assert (tmp_path / "bak" / "COMPLETE").is_file()


def test_a_failed_restore_makes_no_complete_run(setup, tmp_path):
    data, replica = setup
    (replica / "FAIL").touch()
    with pytest.raises(SystemExit, match="failed"):
        backup_from_replica(data, replica, tmp_path / "bak")
    assert not (tmp_path / "bak" / "COMPLETE").exists()


def test_a_damaged_replica_makes_no_complete_run(setup, tmp_path):
    data, replica = setup
    (replica / "fake.db").write_bytes(b"not a database" * 1000)
    with pytest.raises(SystemExit):
        backup_from_replica(data, replica, tmp_path / "bak")
    assert not (tmp_path / "bak" / "COMPLETE").exists()


def test_no_replica_makes_no_complete_run(setup, tmp_path):
    data, _ = setup
    with pytest.raises(SystemExit, match="no replica"):
        backup_from_replica(data, tmp_path / "none", tmp_path / "bak")
    assert not (tmp_path / "bak").exists()


def test_a_stale_replica_is_refused_as_gc_trusts_the_marker(setup, tmp_path):
    data, replica = setup
    with closing(sqlite3.connect(replica / "fake.db")) as conn:
        conn.execute(f"PRAGMA application_id = {int(time.time() // 60) - 4 * 60}")
    with pytest.raises(SystemExit, match="stale"):
        backup_from_replica(data, replica, tmp_path / "bak")
    assert not (tmp_path / "bak" / "COMPLETE").exists()
    backup_from_replica(data, replica, tmp_path / "bak", max_age_hours=0)  # told not to
    assert (tmp_path / "bak" / "COMPLETE").is_file()


def test_a_replica_with_no_heartbeat_is_refused(setup, tmp_path):
    data, replica = setup
    with closing(sqlite3.connect(replica / "fake.db")) as conn:
        conn.execute("PRAGMA application_id = 0")
    with pytest.raises(SystemExit, match="no heartbeat"):
        backup_from_replica(data, replica, tmp_path / "bak")


def test_the_heartbeat_is_a_write_that_the_backup_api_keeps(setup, tmp_path):
    _, replica = setup
    age = heartbeat_age_hours(replica / "fake.db")
    assert age is not None and age < 0.1
