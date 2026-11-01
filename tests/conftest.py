"""Shared fixtures.

Tests that measure time (a linear-time check, a generous bound on something that must
stay quick) are marked @pytest.mark.timing. The tests tox env runs them on their own,
serially, after the rest has run in parallel (-m "not timing", then -m timing with
xdist off), so nothing else loads the machine while they measure. Their bounds still
leave room for coverage tracing and a slow runner: they are there to catch quadratic
behaviour, which is many times slower, not to time things closely (#269)."""

import pytest
from fastapi.testclient import TestClient

from scrap.app import create_app
from scrap.store import new_ulid


@pytest.fixture(autouse=True)
def no_mcp_token(monkeypatch):
    """A token set in the developer's shell must not put /mcp behind auth in tests."""
    monkeypatch.delenv("SCRAP_MCP_TOKEN", raising=False)
    monkeypatch.delenv("SCRAP_MCP_TOKEN_FILE", raising=False)


@pytest.fixture(autouse=True)
def no_publishing(monkeypatch):
    """Publishing settings in the developer's shell must not reach a real site."""
    for name in (
        "SCRAP_PUBLISH_TO", "SCRAP_PUBLISH_SITE", "SCRAP_PUBLISH_TOKEN_FILE",
        "SCRAP_WEB_DIR",
    ):  # fmt: skip
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def loopback_client(monkeypatch):
    """TestClient's default Host is `testserver`, which the Host check (hostguard)
    refuses like any name not in SCRAP_PUBLIC_URL; default to loopback, as a real
    local install is reached."""
    init = TestClient.__init__

    def local(self, app, base_url="http://localhost", *args, **kwargs):
        init(self, app, base_url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", local)


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "data"))


@pytest.fixture
def note(client):
    """A function that captures a note and returns its reference."""

    def capture(text="Shopping list\nmilk and eggs", **extra):
        data = {"id": new_ulid(), "text": text, **extra}
        response = client.post("/api/captures", json=data)
        assert response.status_code == 201, response.text
        return response.json()

    return capture
