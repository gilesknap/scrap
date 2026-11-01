"""Test helpers for public pages: the real receiver (scrap-public/receiver.py, loaded
by path, on a free port over a temporary site folder), scrap's settings pointing at
it, and a page as the PWA's publish mode writes it."""

import importlib.util
import json
import sys
import threading
from http.client import HTTPConnection
from pathlib import Path
from types import ModuleType
from typing import Any

from scrap.publish.checker import CSP

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "s" * 40
WEB = ROOT / "tests" / "data" / "publish_web"  # a stand-in for the PWA's build
SITE = "https://pages.example.org"
NAME = "scrap_public_receiver"


def receiver_module() -> ModuleType:
    if NAME in sys.modules:
        return sys.modules[NAME]
    spec = importlib.util.spec_from_file_location(
        NAME, ROOT / "scrap-public" / "receiver.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = module
    spec.loader.exec_module(module)
    return module


class Site:
    """A running receiver."""

    def __init__(self, folder: Path, **limits: Any) -> None:
        receiver = receiver_module()
        config = receiver.Config(site=folder, token=TOKEN, host="127.0.0.1", port=0)
        for name, value in limits.items():
            setattr(config, name, value)
        self.folder = folder
        self.server = receiver.Server(config)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(
            target=self.server.serve_forever, args=(0.02,), daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        return response.status, json.loads(raw) if raw else None

    def units(self) -> dict[str, dict[str, Any]]:
        status, manifest = self.request("GET", "/v1/manifest")
        assert status == 200, manifest
        return manifest["units"]

    def file(self, unit: str, name: str) -> bytes:
        """A file as nginx would serve it: www/<unit>/<name>."""
        return (self.folder / "www" / unit / name).read_bytes()


def configure(monkeypatch, tmp_path: Path, site: Site | None) -> None:
    """Point scrap's publish settings at site (None: a receiver nobody listens on)."""
    token = tmp_path / "publish-token"
    token.write_text(TOKEN + "\n")
    url = site.url if site else "http://127.0.0.1:9"  # discard: nothing answers
    monkeypatch.setenv("SCRAP_PUBLISH_TO", url)
    monkeypatch.setenv("SCRAP_PUBLISH_SITE", SITE)
    monkeypatch.setenv("SCRAP_PUBLISH_TOKEN_FILE", str(token))
    monkeypatch.setenv("SCRAP_WEB_DIR", str(WEB))


def page(body: str, title: str = "A page", maths: bool = False) -> str:
    """A page as the publish mode writes it."""
    katex = '<link rel="stylesheet" href="/assets/katex.css">' if maths else ""
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
        f"<title>{title}</title>"
        f'<link rel="stylesheet" href="/assets/page.css">{katex}</head>'
        f"<body><article>{body}</article></body></html>"
    )
