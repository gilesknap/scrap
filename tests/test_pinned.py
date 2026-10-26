"""The Pinned page (a list of links the search screen launches from) and topic areas in
search (group:area): one Pinned page however many first pins, none read by Claude."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from scrap import enrich
from scrap.app import create_app
from scrap.store import Store, new_ulid
from scrap.store import topics as topic_store


def jobs(store):
    with store.connect() as conn:
        return conn.execute("SELECT count(*) FROM enrich_job").fetchone()[0]


def both(tmp_path):
    """A client and a store on the same data, to set up what the API cannot."""
    client = TestClient(create_app(tmp_path / "data"))
    return client, Store(tmp_path / "data")


def test_asking_for_the_page_is_not_a_404_before_it_is_made(client):
    assert client.get("/api/pinned").json() is None
    made = client.post("/api/pinned").json()
    assert client.get("/api/pinned").json()["id"] == made["id"]


def test_ensure_makes_the_page_once(client):
    first = client.post("/api/pinned")
    assert first.status_code == 200
    page = first.json()
    assert (page["slug"], page["title"], page["rev"]) == ("pinned", "Pinned", 1)
    assert client.post("/api/pinned").json()["id"] == page["id"]
    assert client.get("/api/pages/pinned").json()["id"] == page["id"]
    assert [p["slug"] for p in client.get("/api/pages").json()] == ["pinned"]


def test_two_first_pins_at_once_make_one_page(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    with ThreadPoolExecutor(4) as pool:
        ids = {
            r.json()["id"]
            for r in pool.map(lambda _: client.post("/api/pinned"), range(8))
        }
    assert len(ids) == 1
    assert len(client.get("/api/pages").json()) == 1


def test_a_page_already_called_pinned_is_it(client, note):
    mine = note("Pinned\n\nmy own words")
    assert mine["slug"] == "pinned"
    assert client.post("/api/pinned").json()["id"] == mine["page_id"]


def test_the_trashed_page_comes_back_not_a_second(client):
    page = client.post("/api/pinned").json()
    client.delete("/api/pages/pinned")
    assert client.get("/api/pages/pinned").status_code == 404
    again = client.post("/api/pinned").json()
    assert again["id"] == page["id"]
    assert client.get("/api/pages/pinned").status_code == 200


def test_pins_survive_a_rename_and_a_concurrent_edit_is_a_409(client):
    page = client.post("/api/pinned").json()
    body = "# Pinned\n\n- [A](/p/a)\n"
    ok = client.patch("/api/pages/pinned", json={"base_rev": 1, "body": body})
    assert ok.status_code == 200
    stale = client.patch("/api/pages/pinned", json={"base_rev": 1, "body": "x"})
    assert stale.status_code == 409  # the client reads again and retries
    renamed = client.patch(
        "/api/pages/pinned", json={"base_rev": 2, "title": "My pins"}
    ).json()
    assert renamed["slug"] == "pinned"  # a slug never changes with the title
    assert client.get(f"/api/pages/{page['id']}").json()["slug"] == "pinned"


def test_claude_does_not_read_the_pinned_page(tmp_path, monkeypatch):
    client, store = both(tmp_path)
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH_DEBOUNCE", "0")
    client.post("/api/pinned")
    client.patch("/api/pages/pinned", json={"base_rev": 1, "body": "- [A](/p/a)\n"})
    assert jobs(store) == 0
    other = client.post("/api/captures", json={"id": new_ulid(), "text": "a note"})
    assert other.status_code == 201
    assert jobs(store) == 1  # the same setup does queue an ordinary page


def test_the_backfill_and_the_related_pass_skip_the_pinned_page(tmp_path):
    client, store = both(tmp_path)
    client.post("/api/pinned")
    note = client.post(
        "/api/captures", json={"id": new_ulid(), "text": "a note"}
    ).json()
    assert enrich.backfill(store, dry_run=True) == 1  # the note alone
    with store.connect() as conn:
        due = [r[0] for r in conn.execute(enrich.STALE, {"all": 1, "limit": 100})]
    assert due == [note["page_id"]]


def test_the_first_pin_is_by_the_one_who_made_it(tmp_path):
    client, store = both(tmp_path)
    client.post("/api/pinned", headers={"Tailscale-User-Login": "me@example.com"})
    with store.connect() as conn:
        who = conn.execute(
            "SELECT author FROM page_rev WHERE page_id = (SELECT id FROM page"
            " WHERE slug = 'pinned')"
        ).fetchall()
    assert [r[0] for r in who] == ["me@example.com"]


# ---- topic areas in search


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    return store


def topic(store, title, tags_of_sources):
    """A topic whose sources carry these tags (one source per tag)."""
    with store.connect() as conn:
        stamp = "2026-10-26T00:00:00Z"
        tid = topic_store.create(
            conn, title, topic_store.topic_key(title), title.lower(), "me", stamp
        )
        ids = []
        for tag in tags_of_sources:
            src = new_ulid()
            conn.execute(
                "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
                " created_at, updated_at) VALUES (?, ?, ?, '', 'note', 0, '{}', ?, ?)",
                (src, src, f"src {src}", stamp, stamp),
            )
            conn.execute("INSERT INTO tag VALUES (?, ?)", (src, tag))
            ids.append(src)
        assert tid
        topic_store.add_sources(conn, tid, ids, "me", stamp)
    return tid


def test_topic_hits_carry_their_area_in_the_order_of_the_index(tmp_path):
    client, store = both(tmp_path)
    topic(store, "Zeta", ["tech/a", "tech/b"])
    topic(store, "Alpha", ["home"])
    topic(store, "Beta", ["tech/c"])
    topic(store, "Bare", [])
    hits = client.get("/api/search", params={"q": "is:topic group:area"}).json()
    assert [(h["title"], h["area"]) for h in hits] == [
        ("Beta", "tech"), ("Zeta", "tech"), ("Alpha", "home"), ("Bare", None),
    ]  # fmt: skip
    index = client.get("/api/topics").json()  # the same order as the Topics screen
    assert [t["title"] for t in index] == [h["title"] for h in hits]
    # an ordinary page has no area key at all
    note = client.post("/api/captures", json={"id": new_ulid(), "text": "tech"}).json()
    plain = client.get("/api/search", params={"q": "tech kind:note"}).json()
    assert note["slug"] in {h["slug"] for h in plain}
    assert all("area" not in h for h in plain)


def test_group_area_never_splits_an_area_across_pages(tmp_path):
    client, store = both(tmp_path)
    for i in range(3):
        topic(store, f"Big {i}", ["big"])
    topic(store, "Small", ["a-small"])
    seen = []
    for offset in (0, 2):
        got = client.get(
            "/api/search",
            params={"q": "is:topic group:area", "limit": 2, "offset": offset},
        ).json()
        seen += [h["area"] for h in got]
    assert seen == ["big", "big", "big", "a-small"]
