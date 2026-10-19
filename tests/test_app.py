import json
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from scrap import __version__
from scrap.app import create_app
from scrap.store import Store, connect, migrate, migrations, new_ulid

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_unknown_route_is_404(client):
    assert client.get("/nope").status_code == 404


def test_migrations_apply_on_a_fresh_dir(tmp_path):
    Store(tmp_path).migrate()
    with Store(tmp_path).connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    Store(tmp_path).migrate()  # idempotent


def test_concurrent_migrations_apply_once(tmp_path):
    dbs = [tmp_path / f"{n}.db" for n in range(4)]
    with ProcessPoolExecutor(4) as pool:
        list(pool.map(migrate, dbs * 4))  # would raise "table blob already exists"
    for db in dbs:
        with closing(connect(db)) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version == len(migrations())


def test_migrate_refuses_a_newer_database(tmp_path):
    with Store(tmp_path).connect() as conn:
        conn.execute("PRAGMA user_version = 999")
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


def _chunks(body: bytes):
    yield from (body[i : i + 256] for i in range(0, len(body), 256))


def test_upload_over_limit_is_413(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_MAX_UPLOAD_MB", "0.001")  # 1048 bytes
    client = TestClient(create_app(tmp_path))
    big = [("file", ("big.bin", b"x" * 2048, "application/octet-stream"))]
    response = client.post("/api/captures", data={"id": new_ulid()}, files=big)
    assert response.status_code == 413
    assert response.json()["detail"].endswith("MB upload limit")
    # Chunked, with no Content-Length: multipart and JSON.
    boundary = "b0undary"
    multipart = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="id"\r\n\r\n'
        f"{new_ulid()}\r\n--{boundary}\r\nContent-Disposition: form-data;"
        f' name="file"; filename="big.bin"\r\n\r\n{"x" * 4096}\r\n--{boundary}--\r\n'
    ).encode()
    note = json.dumps({"id": new_ulid(), "text": "x" * 4096}).encode()
    for body, kind in [
        (multipart, f"multipart/form-data; boundary={boundary}"),
        (note, "application/json"),
    ]:
        response = client.post(
            "/api/captures", content=_chunks(body), headers={"Content-Type": kind}
        )
        assert "content-length" not in response.request.headers
        assert response.status_code == 413
        assert "upload limit" in response.json()["detail"]
    assert not [p for p in (tmp_path / "files").rglob("*") if p.is_file()]
    assert client.get("/api/pages").json() == []


def test_rejected_capture_writes_no_files(client, tmp_path):
    response = client.post(
        "/api/captures",
        data={"id": "bad"},
        files=[("file", ("a.png", PNG, "image/png"))],
    )
    assert response.status_code == 422
    assert not [p for p in (tmp_path / "data/files").rglob("*") if p.is_file()]


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
    one_line = client.patch(url, json={"base_rev": 2, "title": " a\n b "}).json()
    assert one_line["title"] == "a b"


def search(client, query):
    return client.get("/api/search", params={"q": query}).json()


def test_search_finds_title_and_body_at_once(client, note):
    ref = note("Quarterly planning\nbudget for the garden shed")
    note("Something else")
    for query in ["quarterly", "shed", "garden sh", "PLANNING budget"]:
        assert [h["id"] for h in search(client, query)] == [ref["page_id"]]
    assert search(client, 'bad "fts syntax ( OR') == []
    assert "<mark>shed</mark>" in search(client, "shed")[0]["snippet"]
    assert search(client, "\x00") == search(client, "zzz\x00\x01") == []
    assert search(client, "\x00shed")[0]["id"] == ref["page_id"]


def test_snippets_escape_html(client, note):
    note("<b>bold</b> & \x02fake\x03 <script>x</script>")
    snippet = search(client, "bold")[0]["snippet"]
    assert snippet == (
        "&lt;b&gt;<mark>bold</mark>&lt;/b&gt; &amp; fake &lt;script&gt;x&lt;/script&gt;"
    )


def test_slugs(client, note):
    assert note("Café ünïcode")["slug"] == "cafe-unicode"
    assert note("Café")["slug"] == "cafe"
    assert note("Café")["slug"] == "cafe-2"
    assert note("日本語")["slug"] == "page"
    assert note("Café-2 notes")["slug"] == "cafe-2-notes"
    assert note("Café")["slug"] == "cafe-3"


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
    back = client.post(f"/api/pages/{ref['page_id']}/undelete")
    assert (back.status_code, back.json()["title"]) == (200, "Trash me")
    assert len(search(client, "trash")) == 1
    assert client.post(f"/api/pages/{ref['slug']}/undelete").status_code == 404


@pytest.fixture
def shell(tmp_path, monkeypatch):
    """A client whose app serves a stand-in PWA build."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<title>scrap</title>")
    (static / "sw.js").write_text("// sw")
    (static / "assets" / "main-abc.js").write_text("// app")
    monkeypatch.setattr("scrap.app.STATIC", static)
    return TestClient(create_app(tmp_path / "data"))


@pytest.mark.parametrize("path", ["/", "/recent", "/search", "/p/some-slug"])
def test_app_routes_serve_the_pwa(shell, path):
    response = shell.get(path)
    assert response.status_code == 200
    assert response.text == "<title>scrap</title>"
    assert response.headers["cache-control"] == "no-cache"


def test_pwa_files_and_caching(shell):
    sw = shell.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["cache-control"] == "no-cache"
    asset = shell.get("/assets/main-abc.js")
    assert "immutable" in asset.headers["cache-control"]
    assert shell.get("/nope").status_code == 404
    assert shell.get("/api/nope").status_code == 404
    assert shell.get("/healthz").json()["status"] == "ok"


def test_unbuilt_pwa_says_how_to_build(tmp_path, monkeypatch):
    monkeypatch.setattr("scrap.app.STATIC", tmp_path / "missing")
    client = TestClient(create_app(tmp_path / "data"))
    response = client.get("/")
    assert response.status_code == 503
    assert "npm --prefix web run build" in response.text
    assert client.get("/api/pages").status_code == 200


def test_share_fallback_saves_a_capture(client):
    response = client.post(
        "/share",
        data={"title": "A story", "text": "worth reading", "url": "https://e.com/a"},
        files={"files": ("p.png", PNG, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303 and response.headers["location"] == "/"
    [page] = client.get("/api/pages").json()
    assert page["title"] == "A story"
    detail = client.get(f"/api/pages/{page['id']}").json()
    assert detail["captures"][0]["source"] == "share"
    assert detail["captures"][0]["url"] == "https://e.com/a"
    empty = client.post("/share", data={"text": " "}, follow_redirects=False)
    assert empty.status_code == 303
    assert len(client.get("/api/pages").json()) == 1


def test_recent_pages_carry_a_thumbnail(client, note):
    note("no picture")
    files = [
        ("file", ("a.pdf", b"%PDF", "application/pdf")),
        ("file", ("p.png", PNG, "image/png")),
    ]
    response = client.post("/api/captures", data={"id": new_ulid()}, files=files)
    assert response.status_code == 201
    photo, text = client.get("/api/pages").json()
    assert text["thumb"] is None
    assert client.get(f"/api/blobs/{photo['thumb']}").content == PNG


MULTIPART = {"unused": ("u", b"", "text/plain")}  # forces multipart/form-data


def test_line_ends_are_normalised(client):
    """Multipart sends CRLF; JSON clients may send CR or CRLF too."""
    one = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "first\r\nsecond\rthird"},
        files=MULTIPART,
    ).json()
    two = client.post("/api/captures", json={"id": new_ulid(), "text": "a\r\nb"}).json()
    page = client.get(f"/api/pages/{one['page_id']}").json()
    assert page["body"] == "first\nsecond\nthird"
    assert page["captures"][0]["text"] == "first\nsecond\nthird"
    page = client.get(f"/api/pages/{two['page_id']}").json()
    assert page["body"] == "a\nb"
    edit = {"base_rev": page["rev"], "body": "x\r\ny\rz"}
    edited = client.patch(f"/api/pages/{two['page_id']}", json=edit).json()
    assert edited["body"] == "x\ny\nz"
    client.post("/share", data={"text": "s1\r\ns2"}, follow_redirects=False)
    slug = client.get("/api/search?q=s1").json()[0]["slug"]
    assert client.get(f"/api/pages/{slug}").json()["body"] == "s1\ns2"


def test_share_fallback_lifts_a_link_from_text(client):
    client.post(
        "/share",
        data={"title": "A story", "text": "A story https://e.com/s"},
        follow_redirects=False,
    )
    [page] = client.get("/api/pages").json()
    capture = client.get(f"/api/pages/{page['id']}").json()["captures"][0]
    assert (capture["text"], capture["url"]) == ("A story", "https://e.com/s")
