"""The last-opened page (#452): the PWA's report, kept in memory, and MCP
current_page."""

import pytest
from fastapi.testclient import TestClient

from scrap import viewed
from scrap.app import create_app
from scrap.store import Store
from test_mcp import human, ok


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


@pytest.fixture(autouse=True)
def forget():
    viewed.clear()
    yield
    viewed.clear()


def test_unset_is_empty_with_a_message(store):
    out = ok(store, "current_page")
    assert out["page"] is None and out["viewed_at"] is None
    assert "memory" in out["message"]


def test_record_then_current_page(store):
    a, b = human(store, "First\nbody"), human(store, "Second\nbody")
    when = viewed.record(a["page_id"])
    out = ok(store, "current_page")
    assert out["page"]["slug"] == a["slug"] and out["viewed_at"] == when
    assert out["content"]["title"] == "First"
    viewed.record(b["page_id"])  # the latest wins
    assert ok(store, "current_page")["page"]["slug"] == b["slug"]


def test_trashed_page_is_skipped(store):
    p = human(store)
    viewed.record(p["page_id"])
    store.delete_page(p["page_id"])
    out = ok(store, "current_page")
    assert out["page"] is None and "trash" in out["message"]
    store.delete_page(p["page_id"], undo=True)
    assert ok(store, "current_page")["page"]["id"] == p["page_id"]


def test_endpoint_records_and_404s(store, tmp_path):
    p = human(store)
    with TestClient(create_app(tmp_path / "data")) as client:
        assert client.post(f"/api/pages/{p['slug']}/viewed").status_code == 204
        got = viewed.last()
        assert got is not None and got[0] == p["page_id"]
        assert client.post("/api/pages/nope/viewed").status_code == 404
        store.delete_page(p["page_id"])
        viewed.clear()
        assert client.post(f"/api/pages/{p['page_id']}/viewed").status_code == 404
        assert viewed.last() is None
