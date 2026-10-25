"""Shared fixtures.

Tests that measure time (a linear-time check, a generous bound on something that must
stay quick) are marked @pytest.mark.xdist_group("timing"): with --dist loadgroup (the
tests tox env) they all run on one xdist worker, one after another, not against each
other. Their bounds still leave room for coverage tracing and a busy runner: they are
there to catch quadratic behaviour, which is many times slower, not to time things
closely (#269)."""

import pytest
from fastapi.testclient import TestClient

from scrap.app import create_app
from scrap.store import new_ulid


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
