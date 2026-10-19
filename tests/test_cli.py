import subprocess
import sys

from scrap import __version__


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
