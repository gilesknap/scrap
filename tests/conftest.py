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
