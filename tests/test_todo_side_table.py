"""page_todo (migration 18, ADR 36): the table a todo's due, priority and snoozed_until
are in, its constraints, and how each way of writing them keeps it."""

import sqlite3
from contextlib import closing

import pytest

from scrap import retention
from scrap.store import Store, connect, new_ulid, todo
from test_mcp import write

LATER = "2030-01-02"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def rows(store):
    with closing(connect(store.db)) as conn:
        return {
            r["page_id"]: (r["due"], r["priority"], r["snoozed_until"])
            for r in conn.execute("SELECT * FROM page_todo")
        }


def add_page(conn, page_id="A", kind="todo"):
    conn.execute(
        "INSERT INTO page (id, slug, title, kind, fields, created_at, updated_at)"
        " VALUES (?, ?, 'T', ?, '{}', 'x', 'x')",
        (page_id, page_id.lower(), kind),
    )


def test_the_table_refuses_a_bad_date_priority_or_empty_row(store):
    with closing(connect(store.db)) as conn:
        add_page(conn)
        for bad in [
            "(page_id, due) VALUES ('A', '2026-02-30')",
            "(page_id, due) VALUES ('A', 'tomorrow')",
            "(page_id, snoozed_until) VALUES ('A', '2026-11-01T10:00')",
            "(page_id, priority) VALUES ('A', 'urgent')",
            "(page_id) VALUES ('A')",
            "(page_id, due) VALUES ('NOPE', '2026-11-01')",  # no such page
        ]:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(f"INSERT INTO page_todo {bad}")
        conn.execute("INSERT INTO page_todo (page_id, due) VALUES ('A', '2026-11-01')")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("UPDATE page_todo SET due = NULL")  # the last one
        with pytest.raises(sqlite3.IntegrityError):  # one row a page
            conn.execute(
                "INSERT INTO page_todo (page_id, due) VALUES ('A', '2027-01-01')"
            )


def test_write_checks_a_value_and_keeps_the_others(store):
    with closing(connect(store.db)) as conn:
        add_page(conn)
        todo.write(conn, "A", {"due": "2026-11-01", "priority": "low"})
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            todo.write(conn, "A", {"priority": "urgent"})
        assert todo.read(conn, "A") == {
            "due": "2026-11-01", "priority": "low", "snoozed_until": None,
        }  # fmt: skip


def test_clearing_the_last_value_deletes_the_row(store):
    with closing(connect(store.db)) as conn:
        add_page(conn)
        todo.write(conn, "A", {"due": "2026-11-01", "snoozed_until": LATER})
        todo.write(conn, "A", {"due": None})
        assert conn.execute("SELECT count(*) FROM page_todo").fetchone()[0] == 1
        todo.write(conn, "A", {"snoozed_until": None})
        assert conn.execute("SELECT count(*) FROM page_todo").fetchone()[0] == 0
        todo.write(conn, "A", {"due": None})  # nothing to clear: still no row
        todo.write(conn, "A", {})
        assert conn.execute("SELECT count(*) FROM page_todo").fetchone()[0] == 0


def test_the_retention_purge_takes_the_row_with_the_page(store):
    page = write(store, title="Gone", kind="todo", due=LATER, priority="high")
    keep = write(store, title="Kept", kind="todo", due=LATER)
    assert len(rows(store)) == 2
    store.delete_page(page["id"])
    with closing(connect(store.db)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        assert rows(store)  # a trashed todo keeps its row
        retention.purge(conn, "9999-01-01T00:00:00.000Z", "9999-01-01T00:00:00.000Z")
        conn.execute("COMMIT")
    assert list(rows(store)) == [keep["id"]]  # the cascade, not a stray row


def test_a_todo_turned_note_keeps_its_row_and_hides_it(store):
    page = write(store, title="Fix", kind="todo", due=LATER, priority="high")
    store.edit_meta([page["id"]], "me", "web", kind="note")
    assert rows(store)[page["id"]] == (LATER, "high", None)
    shown = store.page(page["id"])
    assert (shown["due"], shown["priority"]) == (None, None)  # hidden for a note
    assert store.search("priority:high", 10) == []
    store.edit_meta([page["id"]], "me", "web", kind="todo")  # back: all there
    shown = store.page(page["id"])
    assert (shown["due"], shown["priority"]) == (LATER, "high")
    assert [h["id"] for h in store.search("priority:high", 10)] == [page["id"]]


def test_each_way_to_set_and_clear_a_value_keeps_the_table_right(store):
    # capture
    c = store.prepare(
        {"id": new_ulid(), "text": "Capture me", "kind": "todo", "due": LATER}, []
    )
    ref = store.capture(c, [], "me")[0]
    assert rows(store) == {ref["page_id"]: (LATER, None, None)}
    # edit (the PWA's patch): set, then clear
    page = store.page(ref["page_id"])
    store.update_page(page["id"], page["rev"], None, None, "me",
                      todo={"priority": "medium", "snoozed_until": LATER})  # fmt: skip
    assert rows(store)[page["id"]] == (LATER, "medium", LATER)
    clear = dict.fromkeys(todo.NAMES)
    store.update_page(page["id"], page["rev"], None, None, "me", todo=clear)
    assert rows(store) == {}
    # append (Claude's, to a page it wrote)
    mine = write(store, title="Mine", kind="todo")
    assert rows(store) == {}
    store.append(mine["id"], new_ulid(), "more", "claude", [], 10_000,
                 todo={"priority": "high"})  # fmt: skip
    assert rows(store) == {mine["id"]: (None, "high", None)}
    store.append(mine["id"], new_ulid(), "again", "claude", [], 10_000,
                 todo={"priority": None})  # fmt: skip
    assert rows(store) == {}
    # import
    p = {
        "slug": "imported", "title": "I", "body": "", "kind": "todo", "tags": [],
        "fields": {"status": "open", "due": LATER, "priority": "urgent"},
        "created_at": "2026-01-01T00:00:00.000Z",
        "updated_at": "2026-01-01T00:00:00.000Z",
    }  # fmt: skip
    store.import_page(p, [(new_ulid(), "note", "", [])], "me")
    (value,) = rows(store).values()
    assert value == (LATER, "high", None)
    # a todo with nothing set has no row
    write(store, title="Plain", kind="todo")
    assert len(rows(store)) == 1
