"""Migration 0018 moves a todo's due, priority and snoozed_until into page_todo.

A database is built at schema 17 by the real runner (the migrations up to 0017 and
their Python steps) and filled with every combination of the three values. Before the
move, the pages are read through a temporary view named page_todo over the old columns
(so today's queries, which name page_todo, run on the old shape); after it, through the
real table. Both must give the same values, search results, lists, exports and MCP
reads, and a second migrate must change nothing."""

import json
from contextlib import closing, contextmanager
from datetime import date, timedelta

import pytest

from scrap import backup
from scrap.__main__ import main
from scrap.store import Store, connect, migrations, new_ulid, todo
from scrap.store.constants import REV_INSERT
from scrap.store.db import AFTER
from scrap.store.indexing import index_page
from test_mcp import ok

TODAY = date.today()


def day(n: int) -> str:
    return (TODAY + timedelta(days=n)).isoformat()


STAMP = "2025-01-01T00:00:00.000Z"
OLD = "2025-01-02T00:00:00.000Z"
BOXES = "Plan\n\n- [x] one\n- [ ] two\n"
# slug, kind, status, due, priority, snoozed_until, trashed, body
PAGES = [
    ("due-only", "todo", "open", day(5), None, None, False, "Fix the gate"),
    ("overdue", "todo", "open", day(-3), None, None, False, "Fix the fence"),
    ("due-today", "todo", "open", day(0), None, None, False, "Fix the shed"),
    ("prio-high", "todo", "open", None, "high", None, False, "Fix the roof"),
    ("prio-low", "todo", "open", None, "low", None, False, "Fix the path"),
    ("prio-med", "todo", "in_progress", None, "medium", None, False, "Fix the hall"),
    ("snz-future", "todo", "open", None, None, day(4), False, "Fix the door"),
    ("snz-past", "todo", "open", None, None, day(-2), False, "Fix the sink"),
    ("all-three", "todo", "open", day(2), "high", day(1), False, BOXES + "tasks"),
    ("none-set", "todo", "open", None, None, None, False, "Fix nothing"),
    ("done-due", "todo", "done", day(-9), "low", None, False, "Fixed it"),
    ("old-stale", "todo", "open", None, None, None, False, "Fix the old thing"),
    ("was-todo", "note", None, day(7), "high", day(3), False, "Once a todo"),
    ("was-todo-2", "consume", None, None, "medium", None, False, "Once a todo too"),
    ("trashed", "todo", "open", day(6), "medium", day(2), True, "Fix the trash"),
    ("a-note", "note", None, None, None, None, False, "Fix a note"),
]
QUERIES = [
    "kind:todo sort:due", "kind:todo sort:priority", "kind:todo sort:due:desc",
    f"kind:todo due:<{day(0)}", f"kind:todo due:<={day(0)}", f"kind:todo due:>{day(0)}",
    f"due:{day(5)}", "due:none", "kind:todo -due:none", "priority:high",
    "priority:none", "-priority:none", "priority:low", "is:snoozed", "-is:snoozed",
    "kind:todo -is:snoozed sort:due", "is:stale", "group:now", "group:due",
    "kind:todo group:now", "kind:todo group:due", "kind:todo -is:done sort:priority",
    "Fix", "fix sort:due", "kind:note due:none", "kind:note priority:high",
]  # fmt: skip
VIEW = (
    "CREATE TEMP VIEW page_todo AS SELECT id AS page_id, due, priority, snoozed_until"
    " FROM page WHERE due IS NOT NULL OR priority IS NOT NULL"
    " OR snoozed_until IS NOT NULL"
)


def build_v17(data):
    """A store folder at schema 17, made by the real migrations, with PAGES."""
    data.mkdir()
    (data / "files").mkdir()
    conn = connect(data / "scrap.db")
    for n, sql in enumerate(migrations()[:17], start=1):
        conn.executescript(f"BEGIN IMMEDIATE;\n{sql}")
        if n in AFTER:
            AFTER[n](conn)
        conn.execute(f"PRAGMA user_version = {n}")
        conn.execute("COMMIT")
    for slug, kind, status, due, prio, snooze, trashed, body in PAGES:
        page_id = new_ulid()
        old = slug == "old-stale"
        conn.execute(
            "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
            " created_at, updated_at, deleted_at, due, priority, snoozed_until,"
            " made_by) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, 'human')",
            (page_id, slug, slug.replace("-", " ").title(), body, kind,
             json.dumps({"status": status} if status else {}), STAMP,
             OLD if old else STAMP, STAMP if trashed else None, due, prio, snooze),
        )  # fmt: skip
        conn.execute(
            REV_INSERT, (page_id, 1, slug, body, "me", "web", OLD if old else STAMP)
        )
        conn.execute("INSERT INTO tag VALUES (?, ?)", (page_id, "home"))
        index_page(conn, page_id)
    conn.execute(
        "UPDATE page SET task_done = 1, task_total = 2 WHERE slug = 'all-three'"
    )
    conn.close()
    return data


@pytest.fixture
def store(tmp_path):
    return Store(build_v17(tmp_path / "data"))


def raw(store):
    with closing(connect(store.db)) as conn:
        return {
            r["slug"]: (r["due"], r["priority"], r["snoozed_until"])
            for r in conn.execute("SELECT * FROM page")
        }


def through_view(store):
    """Every connection the store opens gets the temporary page_todo view."""
    real = store.connect

    @contextmanager
    def connect_with_view():
        with real() as conn:
            conn.execute(VIEW)
            yield conn

    store.connect = connect_with_view


def outputs(store):
    """Everything a reader sees of the todo values, as plain data."""
    with store.connect() as conn:
        slugs = [r[0] for r in conn.execute("SELECT slug FROM page ORDER BY slug")]
        markdown = {
            p["slug"]: backup.page_markdown(conn, p)[0]
            for p in conn.execute("SELECT * FROM page ORDER BY slug")
        }
        ids = {r["slug"]: r["id"] for r in conn.execute("SELECT id, slug FROM page")}
    live = [s for s in slugs if s != "trashed"]
    return {
        "page": {s: strip(store.page(s, trashed=True)) for s in slugs},
        "recent": strip(store.recent(100)),
        "recent_todo": strip(store.recent(100, kind="todo")),
        "search": {q: strip(store.search(q, 100)) for q in QUERIES},
        "markdown": markdown,
        "mcp": {s: ok(store, "read", page=s) for s in live},
        "mcp_search": {q: ok(store, "search", query=q) for q in QUERIES[:8]},
        "ids": ids,
    }


def strip(x):
    """The same data without ids' randomness: ids are kept, the build is one DB."""
    return json.loads(json.dumps(x, default=str))


def table_rows(store):
    with closing(connect(store.db)) as conn:
        return {
            r["slug"]: (r["due"], r["priority"], r["snoozed_until"])
            for r in conn.execute(
                "SELECT slug, t.* FROM page_todo t JOIN page ON id = page_id"
            )
        }


def test_migration_18_moves_the_values_and_changes_nothing_a_reader_sees(store):
    before_raw = raw(store)
    assert any(all(v is None for v in vals) for vals in before_raw.values())
    through_view(store)
    before = outputs(store)
    del store.connect  # the real one again
    store.migrate()
    with closing(connect(store.db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
        assert len(migrations()) >= 18
        columns = {r[1] for r in conn.execute("PRAGMA table_info(page)")}
        assert not columns & {"due", "priority", "snoozed_until"}
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert {"page_todo_by_due", "page_todo_by_snooze"} <= names
        assert not names & {"page_by_due", "page_by_snooze"}
    # Row for row: a row for each page with any value, the same three values
    wanted = {s: v for s, v in before_raw.items() if any(x is not None for x in v)}
    moved = table_rows(store)
    assert moved == wanted
    assert set(wanted.items()) - set(moved.items()) == set()
    assert set(moved.items()) - set(wanted.items()) == set()
    assert len(wanted) == 13 and len(before_raw) == len(PAGES)
    assert outputs(store) == before
    store.migrate()  # again: nothing to do
    assert table_rows(store) == wanted
    assert outputs(store) == before


def test_the_searches_find_something_before_and_after(store):
    """The query list is not vacuous: the todo filters each match some pages."""
    store.migrate()
    hits = {q: [h["slug"] for h in store.search(q, 100)] for q in QUERIES}
    assert hits["kind:todo sort:due"][0] == "done-due"  # the oldest date first
    assert "overdue" in hits[f"kind:todo due:<{day(0)}"]
    assert "was-todo" not in hits["priority:high"]  # a note's value stays hidden
    assert "prio-high" in hits["priority:high"]
    assert set(hits["is:snoozed"]) == {"snz-future", "all-three"}
    assert "old-stale" in hits["is:stale"]
    assert hits["due:none"]


def test_writes_and_a_round_trip_still_work_on_the_migrated_database(store, tmp_path):
    store.migrate()
    clear = dict.fromkeys(todo.NAMES)

    def edit(slug, values):
        page = store.page(slug)
        store.update_page(slug, page["rev"], None, None, "me", todo=values)

    assert table_rows(store)["due-only"] == (day(5), None, None)
    edit("due-only", {"due": None})  # the last value: the row goes
    assert "due-only" not in table_rows(store)
    edit("none-set", {"priority": "low"})  # a migrated todo with none: a row
    assert table_rows(store)["none-set"] == (None, "low", None)
    edit("all-three", {"priority": None, "due": day(9)})  # change and clear
    assert table_rows(store)["all-three"] == (day(9), None, day(1))
    edit("all-three", clear)
    assert "all-three" not in table_rows(store)
    # export, then import into a new store: the three values come back
    edit("all-three", {"due": day(2), "priority": "high", "snoozed_until": day(1)})
    out = tmp_path / "md"
    main(["export", "--data-dir", str(store.dir), str(out)])
    (out / "actions").mkdir()  # import reads a todo by its folder, as a vault has it
    (out / "all-three.md").rename(out / "actions" / "all-three.md")
    other = tmp_path / "other"
    main(["import", "--data-dir", str(other), str(out)])
    with closing(connect(Store(other).db)) as conn:
        got = conn.execute(
            "SELECT t.* FROM page_todo t JOIN page ON id = page_id"
            " WHERE slug = 'all-three'"
        ).fetchone()
    assert (got["due"], got["priority"], got["snoozed_until"]) == (
        day(2), "high", day(1),
    )  # fmt: skip
