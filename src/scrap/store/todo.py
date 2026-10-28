"""Where a todo's own values (due, priority) live: only here.

They are rows of the side table page_todo (ADR 36), one per page with at least one
set. Every SQL reader builds its fragments from col() or cols(), and everything else
reads and writes through read() and write(); tests/test_todo_gate.py fails on any other
mention of them in SQL. (page_todo's snoozed_until column is unused since Snooze was
retired, 28 Oct 2026: nothing reads or writes it; a later migration drops it.)
"""

import sqlite3

NAMES = ("due", "priority")


def col(name: str, p: str = "p") -> str:
    """A SQL expression for one value of the page aliased p (NULL if it has none)."""
    if name not in NAMES:
        raise ValueError(name)
    return f"(SELECT {name} FROM page_todo WHERE page_id = {p}.id)"


def cols(p: str = "p") -> str:
    """The values for a SELECT list, each named as its own (due, priority)."""
    return ", ".join(f"{col(n, p)} AS {n}" for n in NAMES)


def read(conn: sqlite3.Connection, page_id: str) -> dict[str, str | None]:
    """A page's values, None for each it has not."""
    row = conn.execute(
        "SELECT due, priority FROM page_todo WHERE page_id = ?",
        (page_id,),
    ).fetchone()
    return {n: (row[n] if row else None) for n in NAMES}


def write(
    conn: sqlite3.Connection, page_id: str, changes: dict[str, str | None]
) -> None:
    """Set (or clear, with None) the values named in changes; the others are kept.

    The row is deleted when no value is left. A value its CHECK refuses is an
    sqlite3.IntegrityError."""
    if any(n not in NAMES for n in changes):
        raise ValueError(sorted(changes))
    if not changes:
        return
    merged = read(conn, page_id) | changes
    if all(v is None for v in merged.values()):
        conn.execute("DELETE FROM page_todo WHERE page_id = ?", (page_id,))
        return
    conn.execute(
        "INSERT INTO page_todo (page_id, due, priority)"
        " VALUES (?, ?, ?) ON CONFLICT (page_id) DO UPDATE SET"
        " due = excluded.due, priority = excluded.priority",
        (page_id, *(merged[n] for n in NAMES)),
    )
