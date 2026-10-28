"""What a page is (#280, store.roles): each role helper, and its SQL fragment, across
one page of each kind: a typed note, a photo, a page written over MCP, a topic, a gc
review page, an imported page with files and a board."""

import io
import json
from contextlib import closing
from typing import Any

import pytest
from PIL import Image

from scrap import claude, ingest
from scrap.store import CLAUDE, MCP, Store, connect, new_ulid, now, roles, topics
from scrap.store.db import transaction

BOARD = {
    "kind": "whiteboard", "title": "Encoder pipeline", "tags": ["video"],
    "description": "A whiteboard of an encoder pipeline.", "text": "Camera\nEnc",
    "elements": [], "intent": "other", "confidence": "low", "items": [],
}  # fmt: skip
NAMES = ("note", "photo", "mcp", "topic", "review", "import", "board")


def jpeg(colour="red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), colour).save(out, "JPEG")
    return out.getvalue()


def read_as_board(model, system, messages, schema, blob, **kw):
    """claude.complete, faked: every photo is read as a whiteboard."""
    assert schema is claude.SCHEMA
    usage = {"input_tokens": 1, "output_tokens": 1}
    content = [{"type": "text", "text": json.dumps(BOARD)}]
    return claude.Completion(BOARD, content, usage, model, "end_turn")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH", "off")  # photo ingest only: no write-up call
    store = Store(tmp_path / "data")
    store.migrate()
    return store


def capture(store: Store, text: str | None, images=(), **extra: Any) -> str:
    blobs = []
    for colour in images:
        sha, size = store.put_blob(io.BytesIO(jpeg(colour)))
        blobs.append((sha, "image/jpeg", size, None))
    c = store.prepare({"id": new_ulid(), "text": text}, ["image/jpeg"] * len(blobs))
    return store.capture({**c, **extra}, blobs, "me")[0]["page_id"]


@pytest.fixture
def pages(store) -> dict[str, str]:
    """One page of each role, by name: its id. The board's photo is read first, so
    the photo page's stays unread."""
    board = capture(store, None, ["red"])
    worker = ingest.Worker(store, read_as_board)
    while worker.step():
        pass
    out = {
        "board": board,
        "note": capture(store, "Shopping\nmilk"),
        "photo": capture(store, None, ["blue"]),
        "mcp": capture(store, "From Claude\nnotes", source=MCP),
        # As orphans.gather makes one: a file capture with no files, source gc
        "review": capture(
            store, "Orphaned assets", kind="file", source=roles.GC, page_kind="todo"
        ),  # fmt: skip
    }
    with closing(connect(store.db)) as conn, transaction(conn):
        topic = topics.create(conn, "Queues", "queues", "queues", "me", now())
    assert topic is not None
    out["topic"] = topic
    img, size = store.put_blob(io.BytesIO(jpeg("green")))
    pdf, n = store.put_blob(io.BytesIO(b"%PDF"))
    stamp = "2026-01-01T00:00:00.000Z"
    p = {"slug": "imported", "title": "Imported", "body": "notes", "kind": "note",
         "fields": {}, "tags": [], "created_at": stamp,
         "updated_at": stamp}  # fmt: skip
    store.import_page(
        p,
        [(new_ulid(), "note", "notes", [(img, "image/jpeg", size, None)]),
         (new_ulid(), "file", None, [(pdf, "application/pdf", n, None)])],
        "me",
    )  # fmt: skip
    out["import"] = store.page("imported")["id"]
    return out


def each(store: Store, pages: dict[str, str], ask) -> dict[str, Any]:
    with closing(connect(store.db)) as conn:
        return {name: ask(conn, pages[name]) for name in NAMES}


def sql(fragment: str):
    """A fragment on page p, asked of one page."""

    def ask(conn, page_id):
        q = f"SELECT {fragment.format(p='p')} FROM page p WHERE p.id = ?"
        return conn.execute(q, (page_id,)).fetchone()[0]

    return ask


def test_made_by(store, pages):
    want = {"note": "human", "photo": "human", "mcp": "claude", "topic": "topic",
            "review": "gc", "import": "human", "board": "human"}  # fmt: skip
    assert each(store, pages, roles.made_by) == want
    assert each(store, pages, sql(roles.MADE_BY)) == want
    claude_only = {n: n == "mcp" for n in NAMES}
    assert each(store, pages, roles.by_claude) == claude_only
    assert each(store, pages, lambda c, p: bool(sql(roles.BY_CLAUDE)(c, p))) == (
        claude_only
    )
    assert each(store, pages, roles.is_topic) == {n: n == "topic" for n in NAMES}
    review = each(store, pages, lambda c, p: bool(sql(roles.REVIEW)(c, p)))
    assert review == {n: n == "review" for n in NAMES}
    # The page as the PWA reads it says it too (its Written by Claude badge)
    assert {n: store.page(pages[n])["made_by"] for n in NAMES} == want


def test_edited_by_claude(store, pages):
    assert not any(each(store, pages, roles.edited_by_claude).values())
    page = store.page(pages["note"])
    change = lambda c, p: (p["title"], "x")  # noqa: E731
    store.edit_text(page["id"], CLAUDE, change, page["rev"], source=MCP)
    edited = {n: n == "note" for n in NAMES}
    assert each(store, pages, roles.edited_by_claude) == edited
    assert each(store, pages, lambda c, p: bool(sql(roles.CLAUDE_EDITED)(c, p))) == (
        edited
    )
    assert store.edited_by_claude(pages["note"])


def test_maintainer(store, pages):
    # A topic has no capture: enrich's by NOT_BY_INGEST, its kind keeps it out
    want = {"note": "enrich", "photo": "ingest", "mcp": "enrich", "topic": "enrich",
            "review": "ingest", "import": "enrich", "board": "ingest"}  # fmt: skip
    by_sql = each(store, pages, lambda c, p: bool(sql(roles.NOT_BY_INGEST)(c, p)))
    assert by_sql == {n: m == "enrich" for n, m in want.items()}
    enriched = {n: n in ("note", "mcp", "import") for n in NAMES}
    assert each(store, pages, roles.should_enrich) == enriched
    assert each(store, pages, lambda c, p: bool(sql(roles.ENRICHED)(c, p))) == (
        enriched
    )
    # A file page (ADR 38): only gc's review page is one here, a file capture with no
    # files, so file ingest never queues its enrich
    file_first = {n: n == "review" for n in NAMES}
    assert each(store, pages, roles.file_first) == file_first
    assert each(store, pages, lambda c, p: bool(sql(roles.FILE_FIRST)(c, p))) == (
        file_first
    )
    # A capture not yet stored: the kinds prepare makes
    assert [roles.by_ingest(k) for k in ("note", "url", "photo", "file")] == [
        False, False, True, True,
    ]  # fmt: skip


def test_writeup_type(store, pages):
    want = dict.fromkeys(NAMES) | {"topic": "topic", "board": "board"}
    assert each(store, pages, roles.writeup_type) == want
    assert each(store, pages, roles.has_board) == {n: n == "board" for n in NAMES}
    shown = each(store, pages, lambda c, p: bool(sql(roles.SHOWN)(c, p)))
    assert shown == {n: w is not None for n, w in want.items()}


def test_what_automation_may_change(store, pages):
    # The board's title is Claude's now, from its photo: not again
    retitle = {n: n != "board" for n in NAMES}
    untouched = sql(roles.TITLE_UNTOUCHED.replace("{page}", "{p}.id"))
    assert each(store, pages, lambda c, p: bool(untouched(c, p))) == retitle
    page = store.page(pages["note"])
    change = lambda c, p: ("Food", p["body"])  # noqa: E731
    store.edit_text(page["id"], "me", change, page["rev"], source="web")
    assert not each(store, pages, untouched)["note"]
    # Kind: a note nobody filed. An import's and a topic's kind is chosen; a todo's
    # and a whiteboard's is not a note
    unfiled = {n: n in ("note", "photo", "mcp") for n in NAMES}
    rows = each(store, pages, lambda c, p: c.execute(
        "SELECT kind, kind_fixed FROM page WHERE id = ?", (p,)).fetchone())  # fmt: skip
    assert {n: roles.may_rekind(*r) for n, r in rows.items()} == unfiled
    assert each(store, pages, lambda c, p: bool(sql(roles.UNFILED)(c, p))) == unfiled
    assert roles.may_rekind("whiteboard", 0, ("note", "whiteboard"))
    assert roles.may_rekind("todo", 0, ("todo",))
    assert not roles.may_rekind("todo", 1, ("todo",))
    assert not roles.may_rekind("todo", 0)


def test_first_capture(store, pages):
    with closing(connect(store.db)) as conn:
        rows = conn.execute(
            "SELECT c.id, c.page_id, c.kind FROM capture c WHERE c.page_id = ?"
            " ORDER BY c.kind",
            (pages["import"],),
        ).fetchall()
        firsts = {kind: roles.first_capture(conn, cid) for cid, _, kind in rows}
    # An import's main capture is first, its file capture last (received together)
    assert firsts == {
        "file": (pages["import"], False),
        "note": (pages["import"], True),
    }


def test_photos_may_be_added_except_to_a_topic(store, pages):
    assert each(store, pages, roles.takes_photos) == {n: n != "topic" for n in NAMES}


def test_the_pinned_page_is_the_owners_but_never_enriched(store, pages):
    pinned = store.ensure_pinned("me")["id"]
    with closing(connect(store.db)) as conn:
        assert roles.made_by(conn, pinned) == "human"
        assert not roles.should_enrich(conn, pinned)  # a note, but a list of links
        assert sql(roles.NOT_BY_INGEST)(conn, pinned)
        assert not sql(roles.NOT_PINNED)(conn, pinned)
    assert all(each(store, pages, lambda c, p: sql(roles.NOT_PINNED)(c, p)).values())
