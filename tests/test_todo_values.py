"""A todo's due and priority live in page_todo (ADR 36, #267 baseline).

A store is filled with every combination of the values; the searches, writes and
an export/import round trip run on it."""

import json
from contextlib import closing
from datetime import date, timedelta

import pytest

from scrap.__main__ import main
from scrap.store import Store, connect, new_ulid, todo
from scrap.store.constants import REV_INSERT
from scrap.store.indexing import index_page

TODAY = date.today()


def day(n: int) -> str:
    return (TODAY + timedelta(days=n)).isoformat()


STAMP = "2025-01-01T00:00:00.000Z"
OLD = "2025-01-02T00:00:00.000Z"
BOXES = "Plan\n\n- [x] one\n- [ ] two\n"
# slug, kind, status, due, priority, trashed, body
PAGES = [
    ("due-only", "todo", "open", day(5), None, False, "Fix the gate"),
    ("overdue", "todo", "open", day(-3), None, False, "Fix the fence"),
    ("due-today", "todo", "open", day(0), None, False, "Fix the shed"),
    ("prio-high", "todo", "open", None, "high", False, "Fix the roof"),
    ("prio-low", "todo", "open", None, "low", False, "Fix the path"),
    ("prio-med", "todo", "in_progress", None, "medium", False, "Fix the hall"),
    ("all-three", "todo", "open", day(2), "high", False, BOXES + "tasks"),
    ("none-set", "todo", "open", None, None, False, "Fix nothing"),
    ("done-due", "todo", "done", day(-9), "low", False, "Fixed it"),
    ("old-stale", "todo", "open", None, None, False, "Fix the old thing"),
    ("was-todo", "note", None, day(7), "high", False, "Once a todo"),
    ("was-todo-2", "consume", None, None, "medium", False, "Once a todo too"),
    ("trashed", "todo", "open", day(6), "medium", True, "Fix the trash"),
    ("a-note", "note", None, None, None, False, "Fix a note"),
]
QUERIES = [
    "kind:todo sort:due", "kind:todo sort:priority", "kind:todo sort:due:desc",
    f"kind:todo due:<{day(0)}", f"kind:todo due:<={day(0)}", f"kind:todo due:>{day(0)}",
    f"due:{day(5)}", "due:none", "kind:todo -due:none", "priority:high",
    "priority:none", "-priority:none", "priority:low", "is:stale", "group:now",
    "group:due",
    "kind:todo group:now", "kind:todo group:due", "kind:todo -is:done sort:priority",
    "Fix", "fix sort:due", "kind:note due:none", "kind:note priority:high",
]  # fmt: skip


def build(data):
    """A store folder with PAGES."""
    Store(data).migrate()
    conn = connect(data / "scrap.db")
    for slug, kind, status, due, prio, trashed, body in PAGES:
        page_id = new_ulid()
        old = slug == "old-stale"
        conn.execute(
            "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
            " created_at, updated_at, deleted_at, made_by)"
            " VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, 'human')",
            (page_id, slug, slug.replace("-", " ").title(), body, kind,
             json.dumps({"status": status} if status else {}), STAMP,
             OLD if old else STAMP, STAMP if trashed else None),
        )  # fmt: skip
        if due or prio:
            conn.execute(
                "INSERT INTO page_todo (page_id, due, priority) VALUES (?, ?, ?)",
                (page_id, due, prio),
            )
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
    return Store(build(tmp_path / "data"))


def table_rows(store):
    with closing(connect(store.db)) as conn:
        return {
            r["slug"]: (r["due"], r["priority"])
            for r in conn.execute(
                "SELECT slug, t.due, t.priority FROM page_todo t"
                " JOIN page ON id = page_id"
            )
        }


def test_the_searches_find_something(store):
    """The query list is not vacuous: the todo filters each match some pages."""
    hits = {q: [h["slug"] for h in store.search(q, 100)] for q in QUERIES}
    assert hits["kind:todo sort:due"][0] == "done-due"  # the oldest date first
    assert "overdue" in hits[f"kind:todo due:<{day(0)}"]
    assert "was-todo" not in hits["priority:high"]  # a note's value stays hidden
    assert "prio-high" in hits["priority:high"]
    assert "old-stale" in hits["is:stale"]
    assert hits["due:none"]


def test_writes_and_a_round_trip_still_work_on_a_populated_store(store, tmp_path):
    clear = dict.fromkeys(todo.NAMES)

    def edit(slug, values):
        page = store.page(slug)
        store.update_page(slug, page["rev"], None, None, "me", todo=values)

    assert table_rows(store)["due-only"] == (day(5), None)
    edit("due-only", {"due": None})  # the last value: the row goes
    assert "due-only" not in table_rows(store)
    edit("none-set", {"priority": "low"})  # a migrated todo with none: a row
    assert table_rows(store)["none-set"] == (None, "low")
    edit("all-three", {"priority": None, "due": day(9)})  # change and clear
    assert table_rows(store)["all-three"] == (day(9), None)
    edit("all-three", clear)
    assert "all-three" not in table_rows(store)
    # export, then import into a new store: the values come back
    edit("all-three", {"due": day(2), "priority": "high"})
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
    assert (got["due"], got["priority"]) == (day(2), "high")
