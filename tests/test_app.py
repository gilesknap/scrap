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
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "max_upload_bytes": 50 * 2**20,
    }


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


def test_a_capture_embeds_each_image_in_its_text_in_order(client):
    other = PNG.replace(b"\x00", b"\x01", 1)
    files = [
        ("file", ("one.png", PNG, "image/png")),
        ("file", ("doc.pdf", b"%PDF-1.4", "application/pdf")),
        ("file", ("two.png", other, "image/png")),
        ("file", ("again.png", PNG, "image/png")),  # the same photo twice: shown once
    ]
    data = {"id": new_ulid(), "text": "notes"}
    ref = client.post("/api/captures", data=data, files=files).json()
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    one, _, two, _ = (b["sha256"] for b in page["captures"][0]["blobs"])
    embed = "![](/api/blobs/{}/preview?size=2048)".format
    assert page["body"] == f"notes\n\n{embed(one)}\n\n{embed(two)}"
    assert page["title"] == "notes"
    alone = {"id": new_ulid()}
    ref = client.post("/api/captures", data=alone, files=files[:1]).json()
    assert client.get(f"/api/pages/{ref['page_id']}").json()["body"] == embed(one)
    assert [h["slug"] for h in search(client, "api")] == []  # addresses: not words
    shown = {"id": new_ulid(), "text": f"see {embed(two)}"}  # the text shows it already
    ref = client.post("/api/captures", data=shown, files=files[2:3]).json()
    body = client.get(f"/api/pages/{ref['page_id']}").json()["body"]
    assert body == f"see {embed(two)}"


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


def test_capture_kind(client, note):
    board = client.get(f"/api/pages/{note('a board', kind='whiteboard')['page_id']}")
    assert (board.json()["kind"], board.json()["kind_fixed"]) == ("whiteboard", 1)
    plain = client.get(f"/api/pages/{note('plain')['page_id']}").json()
    assert (plain["kind"], plain["kind_fixed"], plain["fields"]) == ("note", 0, {})
    bad = {"id": new_ulid(), "text": "x", "kind": "memory"}  # not offered yet
    assert client.post("/api/captures", json=bad).status_code == 422


def test_edit_kind_fixes_it_and_fills_its_fields(client, note):
    ref = note("https://example.com/a")
    url = f"/api/pages/{ref['page_id']}"
    before = client.get(url).json()
    read = client.patch(url, json={"kind": "consume"}).json()
    assert (read["kind"], read["kind_fixed"], read["rev"]) == ("consume", 1, 1)
    assert read["fields"] == {
        "subtype": "read", "status": "open", "source": "https://example.com/a"
    }  # fmt: skip
    assert read["updated_at"] == before["updated_at"]  # stays put in Recent
    todo = client.patch(url, json={"kind": "todo"}).json()
    assert todo["fields"] == read["fields"]  # kept: status is there already
    done = client.patch(url, json={"fields": {"status": "done"}}).json()
    assert (done["kind"], done["fields"]["status"]) == ("todo", "done")
    same = client.patch(url, json={"kind": "todo", "base_rev": 1, "body": "x"}).json()
    assert (same["fields"], same["rev"], same["body"]) == (done["fields"], 2, "x")
    gone = client.patch(url, json={"fields": {"status": None, "subtype": None}}).json()
    assert gone["fields"] == {"source": "https://example.com/a"}


def test_a_kind_change_keeps_every_field(client, note):
    url = f"/api/pages/{note('imported')['page_id']}"
    imported = {
        "status": "done", "due": "2026-11-01", "priority": 2, "estimate": 1.5,
        "personal": True, "summary": "s" * 200,
    }  # fmt: skip
    first = client.patch(url, json={"kind": "todo", "fields": imported}).json()
    assert first["fields"] == imported  # values of any flat type, as the importer's
    there_and_back = [
        client.patch(url, json={"kind": kind}).json()["fields"]
        for kind in ("note", "consume", "todo")
    ]
    assert there_and_back[0] == imported
    # consume adds its missing default, and it stays: nothing is ever dropped
    assert there_and_back[1] == there_and_back[2] == {**imported, "subtype": "read"}
    fresh = f"/api/pages/{note('fresh')['page_id']}"
    assert client.patch(fresh, json={"kind": "todo"}).json()["fields"] == {
        "status": "open"
    }


@pytest.mark.parametrize(
    "edit",
    [
        {"kind": "memory"},
        {"body": "no base_rev"},
        {"fields": {"a": [1]}},
        {"fields": {"a": {"b": "c"}}},
        {"fields": {"": "empty name"}},
        {"fields": {"k" * 41: "x"}},
        {"fields": {"a": "x" * 201}},
        {"fields": {f"k{n}": "x" for n in range(33)}},
    ],
)
def test_edit_rejects_bad_input(client, note, edit):
    url = f"/api/pages/{note()['page_id']}"
    assert client.patch(url, json=edit).status_code == 422
    assert client.get(url).json()["kind_fixed"] == 0


def test_fields_are_at_most_32_in_all(client, note):
    url = f"/api/pages/{note(kind='todo')['page_id']}"  # status: 1 already
    many = {f"k{n}": "x" for n in range(31)}
    assert client.patch(url, json={"fields": many}).status_code == 200
    more = client.patch(url, json={"fields": {"one": "too many"}})
    assert more.status_code == 422
    assert len(client.get(url).json()["fields"]) == 32


def test_kind_beats_hint_and_works_in_multipart(client, note):
    both = note("both", kind="document", hint="todo")
    assert client.get(f"/api/pages/{both['page_id']}").json()["kind"] == "document"
    data = {"id": new_ulid(), "text": "a form", "kind": "todo"}
    ref = client.post("/api/captures", data=data, files=MULTIPART).json()
    assert client.get(f"/api/pages/{ref['page_id']}").json()["kind"] == "todo"


def test_kind_edit_of_a_page_in_the_trash_is_404(client, note):
    url = f"/api/pages/{note()['page_id']}"
    client.delete(url)
    assert client.patch(url, json={"fields": {"status": "done"}}).status_code == 404
    assert client.patch(url, json={"kind": "todo"}).status_code == 404


def test_stale_edit_leaves_the_kind(client, note):
    url = f"/api/pages/{note()['page_id']}"
    client.patch(url, json={"base_rev": 1, "body": "new"})
    stale = client.patch(url, json={"base_rev": 1, "body": "old", "kind": "todo"})
    assert stale.status_code == 409
    assert client.get(url).json()["kind"] == "note"


def test_edit_tags_replaces_them_all(client, note):
    url = f"/api/pages/{note('tag me')['page_id']}"
    before = client.get(url).json()
    tagged = client.patch(url, json={"tags": ["#Garden  Tools", "diy", "garden tools"]})
    assert tagged.status_code == 200
    page = tagged.json()
    assert sorted(page["tags"]) == ["diy", "garden tools"]  # cleaned, each once
    assert (page["rev"], page["updated_at"]) == (1, before["updated_at"])
    hits = client.get("/api/search", params={"q": "tag:diy"}).json()
    assert [h["id"] for h in hits] == [page["id"]]
    assert client.get("/api/search", params={"q": "tools"}).json()  # indexed
    assert client.get("/api/tags").json() == [["diy", 1, 1], ["garden tools", 1, 1]]
    cleared = client.patch(url, json={"tags": []}).json()
    assert cleared["tags"] == []
    assert client.get("/api/search", params={"q": "tag:diy"}).json() == []
    kept = client.patch(url, json={"fields": {"status": "x"}}).json()
    assert kept["tags"] == []  # no tags in the edit: left as they are


def test_tags_go_with_a_text_edit_and_not_with_a_stale_one(client, note):
    url = f"/api/pages/{note()['page_id']}"
    both = client.patch(url, json={"base_rev": 1, "body": "new", "tags": ["a"]})
    assert (both.json()["rev"], both.json()["tags"]) == (2, ["a"])
    stale = client.patch(url, json={"base_rev": 1, "body": "old", "tags": ["b"]})
    assert stale.status_code == 409
    assert client.get(url).json()["tags"] == ["a"]


@pytest.mark.parametrize(
    "tags",
    [["#"], ["  "], ["x" * 65], [f"t{n}" for n in range(65)], ["\ud800"], [1]],
)
def test_edit_rejects_bad_tags(client, note, tags):
    url = f"/api/pages/{note()['page_id']}"
    client.patch(url, json={"tags": ["keep"]})
    body = json.dumps({"tags": tags})  # a lone surrogate as the escape \ud800
    sent = client.patch(url, content=body, headers={"content-type": "application/json"})
    assert sent.status_code == 422
    assert client.get(url).json()["tags"] == ["keep"]


@pytest.mark.parametrize("field", ["text", "url", "hint", "created_at"])
def test_capture_rejects_a_lone_surrogate(client, field):
    body = json.dumps({"id": new_ulid(), "text": "x", field: "a\ud800b"})
    sent = client.post(
        "/api/captures", content=body, headers={"content-type": "application/json"}
    )
    assert sent.status_code == 422
    assert "ud800" not in sent.text


@pytest.mark.parametrize(
    "edit",
    [
        {"base_rev": 1, "title": "a\ud800"},
        {"base_rev": 1, "body": "a\ud800"},
        {"kind": "\ud800"},
        {"due": "\ud800"},
        {"fields": {"zzkey\ud800": "x"}},
        {"fields": {"k": "\ud800"}},
        {"tags_shown": ["\ud800"]},
    ],
)
def test_edit_rejects_a_lone_surrogate_without_echoing_it(client, note, edit):
    url = f"/api/pages/{note()['page_id']}"
    body = json.dumps(edit)
    sent = client.patch(url, content=body, headers={"content-type": "application/json"})
    assert sent.status_code == 422
    assert "ud800" not in sent.text
    assert "zzkey" not in sent.text  # not even in loc


def test_capture_with_tags_is_tagged_and_indexed_at_once(client):
    data = {"id": new_ulid(), "text": "seed trays", "tags": ["#Garden  Tools", "diy"]}
    ref = client.post("/api/captures", json=data).json()
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert sorted(page["tags"]) == ["diy", "garden tools"]  # cleaned as an edit's
    hits = client.get("/api/search", params={"q": "tag:diy"}).json()
    assert [h["id"] for h in hits] == [ref["page_id"]]
    again = client.post("/api/captures", json={**data, "tags": ["other"]})
    assert again.status_code == 200  # a retry: the first one's tags stay
    assert client.get("/api/tags").json() == [["diy", 1, 1], ["garden tools", 1, 1]]


def test_capture_tags_in_multipart_one_field_each(client):
    data = {"id": new_ulid(), "text": "board", "tags": ["Work", "plans", "work"]}
    files = [("file", ("b.png", PNG, "image/png"))]
    ref = client.post("/api/captures", data=data, files=files).json()
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert sorted(page["tags"]) == ["plans", "work"]
    untagged = client.post("/api/captures", data={"id": new_ulid(), "text": "x"},
                           files=MULTIPART).json()  # fmt: skip
    assert client.get(f"/api/pages/{untagged['page_id']}").json()["tags"] == []


@pytest.mark.parametrize(
    "tags",
    [
        ["#"],
        ["x" * 65],
        [f"t{n}" for n in range(65)],
        ["\ud800"],
        [1],
        "a,b",
        {"a": 1},
        "",
        {},
        0,
        False,  # falsy non-lists too: not "no tags"
    ],
)
def test_capture_rejects_bad_tags(client, tags):
    body = json.dumps({"id": new_ulid(), "text": "x", "tags": tags})
    headers = {"content-type": "application/json"}
    sent = client.post("/api/captures", content=body, headers=headers)
    assert sent.status_code == 422
    assert client.get("/api/pages").json() == []


def test_capture_null_tags_means_none(client):
    body = json.dumps({"id": new_ulid(), "text": "x", "tags": None})
    headers = {"content-type": "application/json"}
    sent = client.post("/api/captures", content=body, headers=headers)
    assert sent.status_code == 201, sent.text
    assert client.get(f"/api/pages/{sent.json()['page_id']}").json()["tags"] == []


def test_pages_by_kind(client, note):
    todo = note("a todo", kind="todo")["slug"]
    plain = note("a note")["slug"]

    def slugs(**params):
        return [p["slug"] for p in client.get("/api/pages", params=params).json()]

    assert slugs(kind="todo") == [todo]
    assert slugs(kind="note") == [plain]
    assert slugs(kind="consume") == []
    assert len(slugs()) == len(slugs(kind="")) == 2
    assert client.get("/api/pages", params={"kind": "bogus"}).status_code == 422


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


def test_search_hits_carry_kind_and_fields(client, note):
    """A hit's row in the PWA has a tick for a todo, so it needs its status."""
    ref = note("Buy a ladder", kind="todo")
    note("Ladder notes")
    hits = {h["id"]: h for h in search(client, "ladder")}
    assert hits[ref["page_id"]]["kind"] == "todo"
    assert hits[ref["page_id"]]["fields"] == {"status": "open"}
    client.patch(f"/api/pages/{ref['page_id']}", json={"fields": {"status": "done"}})
    assert search(client, "buy ladder")[0]["fields"] == {"status": "done"}
    assert all(h["fields"] == {} for h in hits.values() if h["id"] != ref["page_id"])


def test_control_characters_separate_words_in_the_index(client, note):
    ref = note("Odd spacing\nvt\x0bjoined and cr\rsplit\x00here")
    for query in ["joined", "split", "here", "vt"]:
        assert [h["id"] for h in search(client, query)] == [ref["page_id"]], query


def test_snippets_escape_html(client, note):
    note("<b>bold</b> & \x02fake\x03 <script>x</script>")
    snippet = search(client, "bold")[0]["snippet"]
    assert snippet == (
        "&lt;b&gt;<mark>bold</mark>&lt;/b&gt; &amp;  fake  "
        "&lt;script&gt;x&lt;/script&gt;"
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


@pytest.mark.parametrize("path", ["/", "/recent", "/search", "/todos", "/p/some-slug"])
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


def test_text_is_gzipped_and_files_are_not(tmp_path, monkeypatch):
    """Scripts, styles and JSON go gzipped to a client that takes it; stored files,
    previews, downloads, fonts and range requests go as they are."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "excalidraw" / "fonts").mkdir(parents=True)
    (static / "index.html").write_text("<title>scrap</title>")
    (static / "assets" / "big-abc.js").write_text("let x = 1;\n" * 2000)
    (static / "excalidraw" / "fonts" / "f.woff2").write_bytes(b"w" * 5000)
    monkeypatch.setattr("scrap.app.STATIC", static)
    client = TestClient(create_app(tmp_path / "data"))
    gz = {"Accept-Encoding": "gzip"}

    js = client.get("/assets/big-abc.js", headers=gz)
    assert js.headers["content-encoding"] == "gzip" and js.text.startswith("let x")
    assert "Accept-Encoding" in js.headers["vary"]
    assert int(js.headers["content-length"]) < 2000
    plain = client.get("/assets/big-abc.js", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers
    font = client.get("/excalidraw/fonts/f.woff2", headers=gz)
    assert "content-encoding" not in font.headers

    text = "words " * 1000
    files = [("file", ("notes.txt", text.encode(), "text/plain"))]
    ref = client.post("/api/captures", data={"id": new_ulid(), "text": text},
                      files=files).json()  # fmt: skip
    page = client.get(f"/api/pages/{ref['page_id']}", headers=gz)
    assert page.headers["content-encoding"] == "gzip"  # JSON
    sha = page.json()["captures"][0]["blobs"][0]["sha256"]
    blob = client.get(f"/api/blobs/{sha}", headers=gz)
    assert "content-encoding" not in blob.headers and blob.text == text
    part = client.get(f"/api/blobs/{sha}", headers={**gz, "Range": "bytes=0-4"})
    assert part.status_code == 206 and part.content == b"words"
    zipped = client.get(f"/api/pages/{ref['page_id']}/download", headers=gz)
    assert "content-encoding" not in zipped.headers


def test_web_dir_overrides_the_packaged_pwa(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<title>live</title>")
    monkeypatch.setenv("SCRAP_WEB_DIR", str(web))
    client = TestClient(create_app(tmp_path / "data"))
    assert client.get("/recent").text == "<title>live</title>"
    (web / "sw.js").write_text("// new build")  # changes on disk show without a restart
    sw = client.get("/sw.js")
    assert sw.text == "// new build" and sw.headers["cache-control"] == "no-cache"


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


def test_search_ignores_addresses_in_links(client, note):
    note("Links\nsee [the docs](https://docs.example.org/guide) and [[other|a label]]")

    def hit(q):
        return [h["title"] for h in client.get("/api/search", params={"q": q}).json()]

    assert hit("docs") == ["Links"] and hit("label") == ["Links"]
    assert hit("example") == [] and hit("guide") == [] and hit("other") == []


def test_unlink_keeps_labels_in_linear_time():
    import time

    from scrap.store import unlink

    assert unlink("[a](http://x) ![alt](/api/blobs/f/preview?size=2048)") == "a alt"
    assert unlink("[t](<http://x y>) [[s|Label]] [[s]]") == "t Label s"
    assert unlink("[see [[a|Label]]](http://x)") == "see Label"
    line = "[2024-03-02]: met Bob at the cafe"  # not a reference definition to cut
    assert unlink(line) == line
    start = time.monotonic()
    for line in ["[" * 50_000, "[[" * 25_000, "[a](" * 25_000, "![" * 25_000]:
        unlink(line)
    assert time.monotonic() - start < 2


def test_a_line_like_a_reference_definition_stays_searchable(client, note):
    note("Diary\n[2024-03-02]: met Bob at the cafe")
    hits = client.get("/api/search", params={"q": "Bob cafe"}).json()
    assert [h["title"] for h in hits] == ["Diary"]


def test_search_hits_carry_the_same_thumbnail(client, note):
    note("plain words here")
    files = [("file", ("p.png", PNG, "image/png"))]
    data = {"id": new_ulid(), "text": "photo words here"}
    assert client.post("/api/captures", data=data, files=files).status_code == 201
    photo, plain = client.get("/api/pages").json()
    for q in ["words", "after:1w", "is:work", "kind:note"]:
        hits = {h["id"]: h for h in client.get("/api/search", params={"q": q}).json()}
        assert hits[photo["id"]]["thumb"] == photo["thumb"] is not None, q
        assert hits[photo["id"]]["updated_at"] == photo["updated_at"], q
        assert hits[plain["id"]]["thumb"] is None, q


def test_a_heading_as_the_first_line_titles_a_capture_without_its_marks(client, note):
    """`# Trip notes` is titled Trip notes; the text keeps its heading as typed."""
    title = lambda ref: client.get(f"/api/pages/{ref['page_id']}").json()["title"]  # noqa: E731
    ref = note("# Trip notes\nday one")
    assert title(ref) == "Trip notes"
    body = client.get(f"/api/pages/{ref['page_id']}").json()["body"]
    assert body.startswith("# Trip notes")
    assert title(note("   ### Deep heading  \nx")) == "Deep heading"
    assert title(note("#hashtag first\nx")) == "#hashtag first"  # no space: no heading
    assert title(note("#\nx")) == "#"  # nothing but the marks: kept


def test_an_indented_first_line_is_code_and_keeps_its_marks(client, note):
    """Four spaces make `# x` code, not a heading: the title and body keep the #."""
    ref = note("    # indented four\nmore")
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert page["title"] == "# indented four"
    assert page["body"] == "    # indented four\nmore"
    ref = note("\n  \n    # after blank lines  \n")  # blank lines and trailing space go
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert page["title"] == "# after blank lines"
    assert page["body"] == "    # after blank lines"


def who(client, **headers):
    r = client.post(
        "/api/captures", json={"id": new_ulid(), "text": "note"}, headers=headers
    )
    assert r.status_code == 201
    page = client.get(f"/api/pages/{r.json()['page_id']}").json()
    return page["captures"][0]["author"]


def test_author_defaults_to_the_tailscale_header(client, monkeypatch):
    monkeypatch.delenv("SCRAP_IDENTITY_HEADER", raising=False)
    assert who(client, **{"Tailscale-User-Login": "me@example.com"}) == "me@example.com"
    assert who(client, **{"X-Auth-Request-User": "gh-user"}) == "tagged"
    assert who(client) == "tagged"


def test_author_from_a_custom_identity_header(client, monkeypatch):
    monkeypatch.setenv("SCRAP_IDENTITY_HEADER", "X-Auth-Request-User")
    assert who(client, **{"X-Auth-Request-User": "gh-user"}) == "gh-user"
    # the default header is no longer trusted, nor any other
    assert who(client, **{"Tailscale-User-Login": "forged"}) == "tagged"
    assert who(client, **{"X-Auth-Request-Email": "a@b.c"}) == "tagged"
    assert who(client) == "tagged"


def test_blank_identity_header_means_the_default(client, monkeypatch):
    monkeypatch.setenv("SCRAP_IDENTITY_HEADER", " ")
    assert who(client, **{"Tailscale-User-Login": "me@example.com"}) == "me@example.com"


@pytest.mark.parametrize(
    "raw",
    [b"1e400", b"-1e400", b"NaN", b"Infinity", b"-Infinity", b"9007199254740993",
     b"-9007199254740993", b"100000000000000000000000"],
)  # fmt: skip
def test_field_numbers_must_be_finite_and_exact_in_a_browser(client, note, raw):
    url = f"/api/pages/{note()['page_id']}"
    body = b'{"fields": {"n": ' + raw + b"}}"
    sent = client.patch(url, content=body, headers={"content-type": "application/json"})
    assert sent.status_code == 422
    assert client.get(url).json()["fields"] == {}


def test_field_numbers_at_the_limits_are_kept(client, note):
    url = f"/api/pages/{note()['page_id']}"
    edge = {"hi": 2**53, "lo": -(2**53), "f": 1.5e300}
    assert client.patch(url, json={"fields": edge}).json()["fields"] == edge


def test_the_store_refuses_numbers_a_browser_cannot_hold():
    from scrap.store import InvalidError, check_value

    for bad in (float("nan"), float("inf"), -float("inf"), 2**53 + 1):
        with pytest.raises(InvalidError):
            check_value("n", bad)
    check_value("n", True)
    check_value("n", 2**53)


def test_kind_change_on_a_full_page_keeps_every_field(client, note):
    url = f"/api/pages/{note()['page_id']}"
    full = {f"k{n}": "x" for n in range(32)}
    assert client.patch(url, json={"fields": full}).status_code == 200
    for kind in ("todo", "consume"):
        sent = client.patch(url, json={"kind": kind})
        assert sent.status_code == 200, sent.text
        page = sent.json()
        assert page["kind"] == kind and page["fields"] == full  # no room: none added


def test_kind_change_adds_only_the_defaults_that_fit(client, note):
    url = f"/api/pages/{note()['page_id']}"
    thirty = {f"k{n}": "x" for n in range(30)}
    assert client.patch(url, json={"fields": thirty}).status_code == 200
    page = client.patch(url, json={"kind": "consume"}).json()  # subtype, status
    assert len(page["fields"]) == 32
    assert thirty.items() <= page["fields"].items()
    assert page["fields"]["subtype"] == "read"
