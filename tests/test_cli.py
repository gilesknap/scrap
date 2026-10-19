import sqlite3
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from scrap import __version__
from scrap.app import create_app
from scrap.store import new_ulid


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
    conn = sqlite3.connect(data_dir / "scrap.db")
    tables = ["page", "page_rev", "capture", "capture_blob", "blob"]
    rows = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in tables}
    files = {
        p.name: p.read_bytes() for p in (data_dir / "files").rglob("*") if p.is_file()
    }
    return rows, files


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
    assert f"![b.png](files/{png.name})" in (out / "photo.md").read_text()
