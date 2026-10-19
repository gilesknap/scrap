import io
import sqlite3

import pytest
from fastapi.testclient import TestClient

from scrap import __version__
from scrap.app import create_app
from scrap.store import Store, TooLargeError, migrations, new_ulid

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_unknown_route_is_404(client):
    assert client.get("/nope").status_code == 404


def test_migrations_apply_on_a_fresh_dir(tmp_path):
    Store(tmp_path).migrate()
    conn = sqlite3.connect(tmp_path / "scrap.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    Store(tmp_path).migrate()  # idempotent


def test_migrate_refuses_a_newer_database(tmp_path):
    sqlite3.connect(tmp_path / "scrap.db").execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="schema 999"):
        create_app(tmp_path)


def test_connections_enforce_foreign_keys(tmp_path):
    store = Store(tmp_path)
    store.migrate()
    with store.connect() as conn, pytest.raises(sqlite3.IntegrityError):
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        conn.execute(
            "INSERT INTO capture VALUES ('C', 'note', 't', NULL, 'pwa', 'a', 'x', 'x',"
            " 'no-such-page')"
        )


def test_capture_note_makes_a_page(client, note):
    ref = note(hint="todo")
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert page["title"] == "Shopping list"
    assert page["slug"] == ref["slug"] == "shopping-list"
    assert page["body"] == "Shopping list\nmilk and eggs"
    assert (page["kind"], page["kind_fixed"]) == ("todo", 1)
    assert page["fields"] == {"status": "open"}
    assert page["rev"] == 1
    assert page["captures"][0]["author"] == "tagged"
    assert client.get(f"/api/pages/{ref['slug']}").json()["id"] == ref["page_id"]
    assert note()["slug"] == "shopping-list-2"


def test_capture_retry_is_idempotent(client):
    data = {"id": new_ulid(), "text": "once only"}
    first = client.post("/api/captures", json=data)
    again = client.post("/api/captures", json=data)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json() == again.json()
    assert len(client.get("/api/pages").json()) == 1


def test_capture_url_shared_as_text(client, note):
    ref = note("https://example.com/a", hint="consume")
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert page["title"] == "https://example.com/a"
    assert page["captures"][0]["kind"] == "url"
    assert page["fields"]["source"] == "https://example.com/a"


@pytest.mark.parametrize(
    "data",
    [{"text": "no id"}, {"id": "bad", "text": "x"}, {"text": "x", "hint": "y"}, []],
)
def test_capture_rejects_bad_input(client, data):
    if isinstance(data, dict) and "hint" in data:
        data["id"] = new_ulid()
    assert client.post("/api/captures", json=data).status_code == 422
    assert client.post("/api/captures", json={"id": new_ulid()}).status_code == 422


def test_photo_capture_and_blob(client):
    response = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "whiteboard"},
        files=[("file", ("board.png", PNG, "image/png"))],
        headers={"Tailscale-User-Login": "me@example.com"},
    )
    assert response.status_code == 201
    page = client.get(f"/api/pages/{response.json()['page_id']}").json()
    capture = page["captures"][0]
    assert (capture["kind"], capture["author"]) == ("photo", "me@example.com")
    blob = capture["blobs"][0]
    assert (blob["mime"], blob["size"], blob["filename"]) == (
        "image/png",
        40,
        "board.png",
    )
    got = client.get(f"/api/blobs/{blob['sha256']}")
    assert got.content == PNG
    assert got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "path", ["..%2Fscrap.db", "%2e%2e%2f%2e%2e%2fscrap.db", "0" * 64, "A" * 64]
)
def test_blob_path_traversal(client, path):
    assert client.get(f"/api/blobs/{path}").status_code == 404


def test_upload_over_limit_is_413(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_MAX_UPLOAD_MB", "0.001")
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/captures",
        data={"id": new_ulid()},
        files=[("file", ("big.bin", b"x" * 2048, "application/octet-stream"))],
    )
    assert response.status_code == 413
    with pytest.raises(TooLargeError):  # a stream with no Content-Length
        Store(tmp_path).put_blob(io.BytesIO(b"x" * 10), 5)
    assert not [p for p in (tmp_path / "files").rglob("*") if p.is_file()]


def test_stale_edit_is_409(client, note):
    ref = note()
    url = f"/api/pages/{ref['page_id']}"
    edited = client.patch(url, json={"base_rev": 1, "body": "eggs only"})
    assert edited.status_code == 200
    assert (edited.json()["rev"], edited.json()["body"]) == (2, "eggs only")
    stale = client.patch(url, json={"base_rev": 1, "title": "lost"})
    assert stale.status_code == 409
    assert stale.json()["rev"] == 2
    assert client.get(url).json()["title"] == "Shopping list"


def search(client, query):
    return client.get("/api/search", params={"q": query}).json()


def test_search_finds_title_and_body_at_once(client, note):
    ref = note("Quarterly planning\nbudget for the garden shed")
    note("Something else")
    for query in ["quarterly", "shed", "garden sh", "PLANNING budget"]:
        assert [h["id"] for h in search(client, query)] == [ref["page_id"]]
    assert search(client, 'bad "fts syntax ( OR') == []
    assert "<mark>shed</mark>" in search(client, "shed")[0]["snippet"]


def test_search_sees_edits(client, note):
    ref = note("Old title")
    client.patch(
        f"/api/pages/{ref['page_id']}",
        json={"base_rev": 1, "title": "Fresh", "body": "new"},
    )
    assert search(client, "old") == []
    assert len(search(client, "fresh")) == 1


def test_delete_is_soft(client, note, tmp_path):
    ref = note("Trash me")
    keep = note("Keep me")
    assert client.delete(f"/api/pages/{ref['slug']}").status_code == 204
    assert client.get(f"/api/pages/{ref['page_id']}").status_code == 404
    assert client.delete(f"/api/pages/{ref['page_id']}").status_code == 404
    assert [p["id"] for p in client.get("/api/pages").json()] == [keep["page_id"]]
    assert search(client, "trash") == []
    with Store(tmp_path / "data").connect() as conn:  # still stored
        assert conn.execute("SELECT count(*) FROM capture").fetchone()[0] == 2
