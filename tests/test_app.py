from fastapi.testclient import TestClient

from scrap import __version__
from scrap.app import create_app


def test_healthz():
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_unknown_route_is_404():
    client = TestClient(create_app())
    assert client.get("/nope").status_code == 404
