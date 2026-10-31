"""Shared fixtures.

Tests that measure time (a linear-time check, a generous bound on something that must
stay quick) are marked @pytest.mark.timing. The tests tox env runs them on their own,
serially, after the rest has run in parallel (-m "not timing", then -m timing with
xdist off), so nothing else loads the machine while they measure. Their bounds still
leave room for coverage tracing and a slow runner: they are there to catch quadratic
behaviour, which is many times slower, not to time things closely (#269)."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scrap import claude, enrich, ingest
from scrap.app import create_app
from scrap.store import new_ulid


@pytest.fixture(autouse=True)
def no_mcp_token(monkeypatch):
    """A token set in the developer's shell must not put /mcp behind auth in tests."""
    monkeypatch.delenv("SCRAP_MCP_TOKEN", raising=False)
    monkeypatch.delenv("SCRAP_MCP_TOKEN_FILE", raising=False)


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


class FakeClaude:
    """claude.complete, faked. A call's kind is told by its schema, among those the
    subclass names in `schemas` (photo, writeup, topic, discovery or related), and is
    "enrich" for any other; the subclass answers each kind but enrich with answer().
    record() keeps each call in self.calls; an answer that is an exception is raised."""

    schemas: tuple[str, ...] = ()

    def __init__(self):
        self.calls: list[Any] = []

    def answer(self, kind: str, system: Any, messages: Any) -> Any:
        raise NotImplementedError(kind)

    def record(self, kind: str, **call: Any) -> None:
        """Keep the call as a dict: kind, model, system, messages, blob and the rest."""
        self.calls.append({"kind": kind, **call})

    def kinds(self) -> list[str]:
        """The kinds of the calls made, in order (with record() as it is here)."""
        return [c["kind"] for c in self.calls]

    def __call__(self, model, system, messages, schema, blob, **kw):
        by_schema = {
            "photo": claude.SCHEMA,
            "writeup": enrich.WRITEUP_SCHEMA,
            "topic": enrich.TOPIC_SCHEMA,
            "discovery": enrich.DISCOVERY_SCHEMA,
            "related": enrich.RELATED_SCHEMA,
        }
        kind = next((k for k in self.schemas if schema is by_schema[k]), "enrich")
        self.record(
            kind, model=model, system=system, messages=messages, blob=blob, **kw
        )
        if kind == "enrich":
            out = {"tags": [], "summary": "", "title": "",
                   "intent": "other", "confidence": "low", "items": []}  # fmt: skip
        else:
            out = self.answer(kind, system, messages)
        if isinstance(out, BaseException):
            raise out
        usage = {"input_tokens": 1000, "output_tokens": 100}
        content = [{"type": "text", "text": json.dumps(out)}]
        return claude.Completion(out, content, usage, model, "end_turn")


def run_all(store, fake):
    """Run the ingest worker, calling fake for Claude, until no job is left."""
    w = ingest.Worker(store, fake)
    while w.step():
        pass
