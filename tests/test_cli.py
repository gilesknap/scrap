import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from scrap import __version__
from scrap.app import create_app
from scrap.store import Store, new_ulid


def test_cli_version():
    cmd = [sys.executable, "-m", "scrap", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__


def test_cli_serve_runs_uvicorn(monkeypatch):
    from scrap.__main__ import main

    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: calls.append((a, kw)))
    main(["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert calls == [
        (
            ("scrap.app:create_app",),
            {"factory": True, "host": "0.0.0.0", "port": 9000},
        )
    ]


def _dump(data_dir):
    tables = ["page", "page_rev", "capture", "capture_blob", "blob"]
    with Store(data_dir).connect() as conn:
        rows = {
            t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in tables
        }
    files = {
        p.name: p.read_bytes() for p in (data_dir / "files").rglob("*") if p.is_file()
    }
    return {t: [tuple(r) for r in v] for t, v in rows.items()}, files


def test_backup_restore_round_trip(client, note, tmp_path):
    from scrap.__main__ import main

    data = tmp_path / "data"
    note("Plain note")
    client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "Board\nwith arrows"},
        files=[("file", ("b.png", b"png bytes", "image/png"))],
    )
    main(["backup", "--data-dir", str(data), str(tmp_path / "bak")])
    main(["restore", "--data-dir", str(tmp_path / "new"), str(tmp_path / "bak")])
    assert _dump(tmp_path / "new") == _dump(data)
    with pytest.raises(SystemExit, match="not empty"):
        main(["restore", "--data-dir", str(data), str(tmp_path / "bak")])
    main(["restore", "--force", "--data-dir", str(data), str(tmp_path / "bak")])
    restored = TestClient(create_app(tmp_path / "new"))
    assert (
        restored.get("/api/search", params={"q": "arrows"}).json()[0]["title"]
        == "Board"
    )


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores permissions"
)
def test_restore_from_a_read_only_backup(client, note, tmp_path):
    from scrap.__main__ import main

    data, bak = tmp_path / "data", tmp_path / "bak"
    note("From read-only media")
    client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "Photo"},
        files=[("file", ("b.png", b"png bytes", "image/png"))],
    )
    main(["backup", "--data-dir", str(data), str(bak)])
    assert sorted(p.name for p in bak.iterdir()) == ["files", "scrap.db"]
    dirs = [bak, *(p for p in bak.rglob("*") if p.is_dir())]
    for path in dirs:
        path.chmod(0o555)
    try:
        main(["restore", "--data-dir", str(tmp_path / "new"), str(bak)])
        main(["restore", "--force", "--data-dir", str(data), str(bak)])
    finally:
        for path in dirs:
            path.chmod(0o755)
    assert _dump(tmp_path / "new") == _dump(data)
    assert sorted(p.name for p in (tmp_path / "new").iterdir()) == ["files", "scrap.db"]


def test_export_markdown(client, note, tmp_path, capsys):
    from scrap.__main__ import main

    note("Kept\nbody text")
    client.delete(f"/api/pages/{note('Binned')['page_id']}")
    client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "Photo"},
        files=[("file", ("b.png", b"png bytes", "image/png"))],
    )
    out = tmp_path / "md"
    main(["export", "--data-dir", str(tmp_path / "data"), str(out)])
    assert "exported 2 pages" in capsys.readouterr().out
    assert sorted(p.name for p in out.glob("*.md")) == ["kept.md", "photo.md"]
    kept = (out / "kept.md").read_text()
    assert kept.startswith('---\ntitle: "Kept"\n') and "body text" in kept
    [png] = (out / "files").iterdir()
    assert png.read_bytes() == b"png bytes"
    photo = (out / "photo.md").read_text()
    assert f"![b.png](files/{png.name})" in photo  # the text's embed, pointed here
    assert photo.count(png.name) == 1 and "/api/blobs" not in photo


def test_restore_refuses_a_bad_backup_without_touching_data(note, tmp_path):
    from scrap.__main__ import main

    data, bak = tmp_path / "data", tmp_path / "bak"
    note("Keep me")
    main(["backup", "--data-dir", str(data), str(bak)])
    before = _dump(data)
    with Store(bak).connect() as conn:
        conn.execute("PRAGMA user_version = 7")
    for target in [data, tmp_path / "new"]:
        with pytest.raises(SystemExit, match="schema 7"):
            main(["restore", "--force", "--data-dir", str(target), str(bak)])
    (bak / "scrap.db").write_bytes(b"not a database" * 100)
    with pytest.raises(SystemExit, match="bad backup"):
        main(["restore", "--force", "--data-dir", str(data), str(bak)])
    assert _dump(data) == before
    assert not (tmp_path / "new").exists()
    assert sorted(p.name for p in data.iterdir()) == [
        "files",
        "scrap.db",
        "scrap.db.lock",
    ]
