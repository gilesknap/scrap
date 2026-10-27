"""Where a todo's own values (due, priority, snoozed_until) live: only here.

Every SQL reader builds its fragments from col() or cols(), and everything else reads
and writes through read() and write(). Today the values are columns of page; keeping
that knowledge in this module is what lets them move without touching a caller
(tests/test_todo_gate.py fails on any other mention of them in SQL).
"""

import sqlite3

NAMES = ("due", "priority", "snoozed_until")


def col(name: str, p: str = "p") -> str:
    """A SQL expression for one value of the page aliased p (NULL if it has none)."""
    if name not in NAMES:
        raise ValueError(name)
    return f"{p}.{name}"


def cols(p: str = "p") -> str:
    """The three values for a SELECT list, each named as its own (due, priority...)."""
    return ", ".join(f"{col(n, p)} AS {n}" for n in NAMES)


def read(conn: sqlite3.Connection, page_id: str) -> dict[str, str | None]:
    """A page's three values, None for each it has not."""
    row = conn.execute(
        f"SELECT {cols('p')} FROM page p WHERE p.id = ?", (page_id,)
    ).fetchone()
    return {n: (row[n] if row else None) for n in NAMES}


def write(
    conn: sqlite3.Connection, page_id: str, changes: dict[str, str | None]
) -> None:
    """Set (or clear, with None) the values named in changes; the others are kept.

    A value its CHECK refuses is an sqlite3.IntegrityError."""
    if any(n not in NAMES for n in changes):
        raise ValueError(sorted(changes))
    if not changes:
        return
    sets = ", ".join(f"{n} = ?" for n in changes)  # names from NAMES only
    conn.execute(f"UPDATE page SET {sets} WHERE id = ?", (*changes.values(), page_id))
