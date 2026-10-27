"""Who made a page, stored (#280 step 3), and where a text revision came from (#153):
migration 16, each way a page is made, and that neither changes afterwards."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client

from old_schema import undo_0018
from scrap import mcp_server, orphans
from scrap.app import create_app
from scrap.store import CLAUDE, MCP, Store, new_ulid, now, roles, topics
from scrap.store.db import AFTER, connect, migrations, transaction
from scrap.store.fixes import add_made_by

T1, T2, T3 = (f"2026-01-0{d}T00:00:00.000Z" for d in (1, 2, 3))

# The v15 fixture's pages: id -> (captures as (kind, source, received_at), made_by)
V15 = {
    "NOTE": ([("note", "pwa", T1)], "human"),
    "SHARE": ([("url", "share", T1)], "human"),
    "PHOTO": ([("photo", "pwa", T1)], "human"),
    "MCP": ([("note", "mcp", T1)], "claude"),
    "APPENDED": ([("note", "mcp", T1), ("note", "mcp", T2)], "claude"),
    # Never made by scrap (Store.append refuses it): the first capture decides
    "LATE_MCP": ([("note", "pwa", T1), ("note", "mcp", T2)], "human"),
    "REVIEW": ([("file", "gc", T1)], "gc"),
    "TOPIC": ([], "topic"),
    "IMPORT": ([("note", "import", T1), ("file", "import", T1)], "human"),
    "PINNED": ([], "human"),
    "TRASHED_MCP": ([("note", "mcp", T1)], "claude"),
}
# Text revisions: (page, rev, author) -> source after migration 16
REVS = {
    ("NOTE", 1, "me@example.com"): "web",
    ("NOTE", 2, CLAUDE): "mcp",  # task boxes Claude added (actions.append)
    ("NOTE", 3, "tagged"): "web",
    ("MCP", 1, CLAUDE): "mcp",
    ("MCP", 2, CLAUDE): "mcp",
    ("TOPIC", 1, "claude-sonnet"): "web",  # the producer, not claude
    ("REVIEW", 1, "scrap gc"): "web",
}


def v15(data):
    """A store folder whose database is at schema 15 (no made_by, no page_rev.source),
    with a page of each kind."""
    data.mkdir()
    (data / "files").mkdir()
    conn = connect(data / "scrap.db")
    for n, sql in enumerate(migrations()[:15], start=1):
        conn.executescript(f"BEGIN IMMEDIATE;\n{sql}")
        if n in AFTER:
            AFTER[n](conn)
        conn.execute(f"PRAGMA user_version = {n}")
        conn.execute("COMMIT")
    for page_id, (captures, _) in V15.items():
        deleted = T3 if page_id.startswith("TRASHED") else None
        slug = "pinned" if page_id == "PINNED" else page_id.lower()
        conn.execute(
            "INSERT INTO page (id, slug, title, created_at, updated_at, deleted_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (page_id, slug, page_id.title(), T1, T1, deleted),
        )
        for i, (kind, source, received) in enumerate(captures):
            conn.execute(
                "INSERT INTO capture VALUES (?, ?, 'x', NULL, ?, 'me', ?, ?, ?)",
                (f"{page_id}-{i}", kind, source, received, received, page_id),
            )
    conn.execute("INSERT INTO topic VALUES ('TOPIC', 'queues', ?)", (T1,))
    for page_id, rev, author in REVS:  # page_rev as it was: six columns
        conn.execute(
            "INSERT INTO page_rev VALUES (?, ?, 't', 'b', ?, ?)",
            (page_id, rev, author, T1),
        )
    conn.close()
    return data


def made(store: Store) -> dict[str, str]:
    with store.connect() as conn:
        return dict(conn.execute("SELECT id, made_by FROM page").fetchall())


def sources(store: Store) -> dict[tuple[str, int, str], str]:
    with store.connect() as conn:
        rows = conn.execute("SELECT page_id, rev, author, source FROM page_rev")
        return {(p, r, a): s for p, r, a, s in rows}


def test_migration_16_backfills_made_by_and_revision_sources(tmp_path):
    store = Store(v15(tmp_path / "data"))
    store.migrate()
    assert made(store) == {page_id: by for page_id, (_, by) in V15.items()}
    assert sources(store) == REVS
    with store.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
        assert len(migrations()) >= 16
        with pytest.raises(sqlite3.IntegrityError, match="made_by"):  # the CHECK
            conn.execute(
                "INSERT INTO page (id, slug, title, created_at, updated_at, made_by)"
                " VALUES ('X', 'x', 'X', ?, ?, 'robot')",
                (T1, T1),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO page_rev (page_id, rev, title, body, author, source,"
                " created_at) VALUES ('NOTE', 9, 't', 'b', 'me', 'pwa', ?)",
                (T1,),
            )
    # is:claude: the pages Claude wrote, out of the trash
    assert {h["id"] for h in store.search("is:claude", 50)} == {"MCP", "APPENDED"}
    assert {h["id"] for h in store.search("is:claude-edited", 50)} == {"NOTE", "MCP"}


def test_migration_16_can_run_again(tmp_path):
    store = Store(v15(tmp_path / "data"))
    store.migrate()
    with closing(connect(store.db)) as conn, transaction(conn):
        add_made_by(conn)  # again: nothing to do
        undo_0018(conn)
        conn.execute("PRAGMA user_version = 15")
    store.migrate()
    assert made(store)["MCP"] == "claude" and sources(store) == REVS


def test_an_older_schema_reads_who_made_a_page_as_before(tmp_path):
    """Before migration 16, the Python helpers work made_by and edited_by_claude out
    as they were (Store.page on a database not yet migrated). The SQL fragments read
    the columns: scrap gc expects the database the service has already migrated."""
    store = Store(v15(tmp_path / "data"))
    with closing(connect(store.db)) as conn:
        assert {p: roles.made_by(conn, p) for p in V15} == {
            page_id: by for page_id, (_, by) in V15.items()
        }
        assert roles.by_claude(conn, "MCP") and not roles.by_claude(conn, "LATE_MCP")
        assert roles.edited_by_claude(conn, "NOTE")
        assert not roles.edited_by_claude(conn, "PHOTO")


# ---- made once, by each way a page is made


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "data"))


@pytest.fixture
def store(client, tmp_path):
    return Store(tmp_path / "data")


def call(store: Store, tool: str, **args: Any) -> Any:
    async def main():
        async with Client(mcp_server.server(store)) as c:
            return await c.call_tool(tool, args)

    result = anyio.run(main)
    assert not result.is_error, result.content
    return result.structured_content


def capture(client, headers=None, **data: Any) -> str:
    r = client.post(
        "/api/captures",
        json={"id": new_ulid(), "text": "Shopping\nmilk", **data},
        headers=headers or {},
    )
    assert r.status_code == 201, r.text
    return r.json()["page_id"]


def made_by(store: Store, key: str) -> str:
    return store.page(key, trashed=True)["made_by"]


def test_each_way_a_page_is_made_sets_made_by(client, store):
    assert made_by(store, capture(client)) == "human"  # the PWA
    assert made_by(store, capture(client, source="share")) == "human"
    photo = client.post(
        "/api/captures",
        data={"id": new_ulid()},
        files=[("file", ("p.png", b"png bytes", "image/png"))],
    )
    assert made_by(store, photo.json()["page_id"]) == "human"
    mine = call(store, "write", title="T", body="B", origin="o")
    assert made_by(store, mine["id"]) == "claude"  # over MCP
    when = datetime(2026, 10, 24, 9, tzinfo=UTC)
    review = orphans._create(store, "Orphaned assets 2026-10", "files", when)
    assert made_by(store, review) == "gc"  # scrap gc's review page
    with store.connect() as conn, transaction(conn):
        topic = topics.create(conn, "Queues", "queues", "queues", "claude-x", now())
    assert topic and made_by(store, topic) == "topic"
    p = {"slug": "imported", "title": "Imported", "body": "notes", "kind": "note",
         "fields": {}, "tags": [], "created_at": T1, "updated_at": T1}  # fmt: skip
    store.import_page(p, [(new_ulid(), "note", "notes", [])], "me")
    assert made_by(store, "imported") == "human"  # its captures' source is import
    assert store.ensure_pinned("me")["made_by"] == "human"


def test_made_by_never_changes(client, store):
    mine = call(store, "write", title="Log", body="first", origin="o")
    theirs = capture(client)
    for page in (mine["id"], theirs):  # edits, a kind change, photos, the trash
        rev = store.page(page)["rev"]
        r = client.patch(f"/api/pages/{page}", json={"base_rev": rev, "body": "new"})
        assert r.status_code == 200, r.text
        assert client.patch(f"/api/pages/{page}", json={"kind": "todo"}).is_success
        store.edit_meta([page], "me", "web", kind="document")
        call(store, "edit_meta", pages=[page], kind="note")
        call(store, "edit_page", page=page, old="new", new="newer")
        r = client.post(
            f"/api/pages/{page}/captures",
            data={"id": new_ulid()},
            files=[("file", ("p.png", page.encode(), "image/png"))],
        )
        assert r.status_code in (200, 201), r.text
        store.delete_page(page)
        store.delete_page(page, undo=True)
    call(store, "write", title="Log", append_to=mine["slug"], body="more", origin="o")
    assert made_by(store, mine["id"]) == "claude"
    assert made_by(store, theirs) == "human"
    # Claude's edits of the owner's page are is:claude-edited, never is:claude
    assert [h["id"] for h in store.search("is:claude", 50)] == [mine["id"]]
    assert {h["id"] for h in store.search("is:claude-edited", 50)} == {
        mine["id"],
        theirs,
    }
    with store.connect() as conn, pytest.raises(sqlite3.IntegrityError, match="never"):
        conn.execute("UPDATE page SET made_by = 'claude' WHERE id = ?", (theirs,))
    with store.connect() as conn:  # the same value is no change
        conn.execute("UPDATE page SET made_by = 'human' WHERE id = ?", (theirs,))


def test_the_badge_and_mcp_read_say_who_made_it(client, store):
    mine = call(store, "write", title="Log", body="first", origin="o")
    theirs = capture(client)
    assert client.get(f"/api/pages/{mine['id']}").json()["made_by"] == "claude"
    assert client.get(f"/api/pages/{theirs}").json()["made_by"] == "human"
    assert call(store, "read", page=mine["id"])["page"]["written_by_claude"] is True
    assert call(store, "read", page=theirs)["page"]["written_by_claude"] is False


# ---- #153: no request header makes a change Claude's


@pytest.mark.parametrize("header", ["Tailscale-User-Login", "X-Auth-Request-User"])
@pytest.mark.parametrize("value", ["claude", "Claude", " claude ", "mcp", "gh-user"])
def test_a_web_request_never_makes_a_claude_revision(
    client, store, monkeypatch, header, value
):
    if header != "Tailscale-User-Login":
        monkeypatch.setenv("SCRAP_IDENTITY_HEADER", header)
    page = capture(client, {header: value})
    for body in ("one", "two"):
        rev = store.page(page)["rev"]
        r = client.patch(
            f"/api/pages/{page}", json={"base_rev": rev, "body": body},
            headers={header: value},
        )  # fmt: skip
        assert r.status_code == 200, r.text
    author = "tagged" if value.strip().lower() == "claude" else value
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT author, source FROM page_rev WHERE page_id = ?", (page,)
        ).fetchall()
        captured = conn.execute(
            "SELECT author FROM capture WHERE page_id = ?", (page,)
        ).fetchone()[0]
    assert {tuple(r) for r in rows} == {(author, "web")} and len(rows) == 3
    assert captured == author
    assert store.search("is:claude-edited", 50) == []


def test_the_identity_header_is_the_author_and_source_is_web(
    client, store, monkeypatch
):
    monkeypatch.setenv("SCRAP_IDENTITY_HEADER", "X-Auth-Request-User")
    who = {"X-Auth-Request-User": "gh-user", "Tailscale-User-Login": "claude"}
    page = capture(client, who)
    r = client.patch(f"/api/pages/{page}", json={"base_rev": 1, "body": "x"},
                     headers=who)  # fmt: skip
    assert r.status_code == 200, r.text
    text = store.revisions(page)["text"]
    assert [(t["author"], t["source"]) for t in text] == [("gh-user", "web")] * 2
    assert store.text_revision(page, 2)["source"] == "web"


def test_claude_revisions_are_source_mcp_and_fold_by_source(client, store):
    page = capture(client)
    call(store, "edit_page", page=page, old="milk", new="oat milk")
    call(store, "edit_page", page=page, old="oat", new="soy")  # folds into the last
    text = store.revisions(page)["text"]
    assert [(t["rev"], t["author"], t["source"]) for t in text] == [
        (3, CLAUDE, MCP), (1, "tagged", "web"),
    ]  # fmt: skip
    # The same author from another source is not folded into Claude's
    store.edit_text(page, CLAUDE, lambda c, p: (p["title"], "web"), source="web")
    assert [t["source"] for t in store.revisions(page)["text"]][:2] == ["web", MCP]


@pytest.mark.parametrize(
    ("value", "want"),
    [("gh-user", "gh-user"), ("claude", "tagged"), (" CLAUDE ", "tagged"),
     ("   ", "tagged"), ("", "tagged")],
)  # fmt: skip
def test_author_ignores_a_blank_header_or_one_naming_claude(monkeypatch, value, want):
    from starlette.requests import Request

    from scrap.uploads import author

    monkeypatch.setenv("SCRAP_IDENTITY_HEADER", "X-Auth-Request-User")
    headers = [(b"x-auth-request-user", value.encode())]
    assert author(Request({"type": "http", "headers": headers})) == want
