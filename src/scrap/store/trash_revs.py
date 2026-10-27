"""The trash's history (#332): page_trash_rev, a row each time a page goes
to the trash or comes back from it, by whom and from where, so revisions and its
recent-changes feed show deletes; the pages one call moves to the trash share a batch
id, and undelete brings a batch back at once. Below trash and revisions, which use it.
"""

import sqlite3
from typing import Any

TRASH = "trash"  # an action: the page went to the trash
RESTORE = "restore"  # it came back
# Every move into or out of the trash, with its page's slug (null once purged: the
# row goes with the page, ON DELETE CASCADE, so in practice never)
TRASH_REV = (
    "SELECT r.id, r.page_id, p.slug, r.action, r.author, r.source, r.batch_id,"
    " r.created_at FROM page_trash_rev r JOIN page p ON p.id = r.page_id"
)


def record(
    conn: sqlite3.Connection,
    page_id: str,
    action: str,
    author: str,
    source: str,
    batch: str | None,
    stamp: str,
) -> None:
    """A page went to the trash, or came back from it."""
    conn.execute(
        "INSERT INTO page_trash_rev (page_id, action, author, source, batch_id,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (page_id, action, author, source, batch, stamp),
    )


def trash_revs(
    conn: sqlite3.Connection,
    page_id: str | None,
    batch: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """The moves into and out of the trash, newest first, at most limit: a page's, a
    batch's (with page_id, that page's in it), or with neither every page's."""
    where, args = ["1"], []
    if page_id is not None:
        where.append("r.page_id = ?")
        args.append(page_id)
    if batch is not None:
        where.append("r.batch_id = ?")
        args.append(batch)
    sql = f"{TRASH_REV} WHERE {' AND '.join(where)} ORDER BY r.id DESC LIMIT ?"
    return [dict(row) for row in conn.execute(sql, (*args, limit))]


def in_batch(conn: sqlite3.Connection, batch: str) -> tuple[list[str], list[str]]:
    """The pages a batch moved to the trash: (those still there from it, those not:
    brought back since, or moved to the trash again by a later call)."""
    rows = conn.execute(
        "SELECT r.page_id, p.deleted_at IS NOT NULL AND r.id = (SELECT max(l.id)"
        " FROM page_trash_rev l WHERE l.page_id = r.page_id) AS there"
        " FROM page_trash_rev r JOIN page p ON p.id = r.page_id"
        " WHERE r.batch_id = ? AND r.action = ? ORDER BY r.id",
        (batch, TRASH),
    ).fetchall()
    return [r[0] for r in rows if r[1]], [r[0] for r in rows if not r[1]]
