"""The trash, and when a page in it is purged (nightly ``scrap gc``, scrap.retention:
#276)."""

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .core import Core
from .db import _rows
from .errors import NoSuchPage
from .helpers import now
from .roles import IS_TOPIC
from .topics import touch

TRASH_DAYS = 30.0  # a page stays in the trash this long before gc purges it
MAX_DAYS = 36500  # the longest retention: a hundred years
# A page's columns as the trash lists it; topic: never purged (its key is a veto)
COLUMNS = (
    "id, slug, title, kind, deleted_at, updated_at,"
    f" {IS_TOPIC.format(p='page')} AS topic"
)


def trash_days() -> float | None:
    """How long a page stays in the trash, as the server says it (SCRAP_TRASH_DAYS, set
    as the gc that purges it is: default 30, at least 1); None for off: nothing purges
    this store's trash, so no page shows a purge date."""
    value = os.environ.get("SCRAP_TRASH_DAYS", "").strip()
    if not value:
        return TRASH_DAYS
    if value.lower() == "off":
        return None
    try:
        days = float(value)
    except ValueError:
        days = 0.0
    if not 1 <= days <= MAX_DAYS:
        raise SystemExit(
            f"SCRAP_TRASH_DAYS must be a number of days (1 to {MAX_DAYS}) or off,"
            f" not {value!r}"
        )
    return days


def purge_at(deleted_at: str | None, days: float | None, topic: bool) -> str | None:
    """When a page in the trash is due for its purge (the first nightly gc from then
    purges it); None if it never is: not in the trash, a topic, or purging off."""
    if deleted_at is None or days is None or topic:
        return None
    try:
        when = datetime.fromisoformat(deleted_at) + timedelta(days=days)
    except ValueError:
        return None
    return (
        when.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def with_purge(row: dict[str, Any]) -> dict[str, Any]:
    """A trash row with purge_at (see purge_at), topic a bool."""
    row["topic"] = bool(row["topic"])
    row["purge_at"] = purge_at(row["deleted_at"], trash_days(), row["topic"])
    return row


def restore_in(conn: sqlite3.Connection, page_id: str) -> None:
    """Bring a page back from the trash; its topics are due again (#261)."""
    conn.execute("UPDATE page SET deleted_at = NULL WHERE id = ?", (page_id,))
    touch(conn, page_id, now())


class TrashMixin(Core):
    def trash(self, limit: int) -> list[dict[str, Any]]:
        """The pages in the trash, most recently deleted first: id, slug, title, kind,
        deleted_at, updated_at, topic and purge_at."""
        with self.connect() as conn:
            rows = _rows(
                conn,
                f"SELECT {COLUMNS} FROM page WHERE deleted_at IS NOT NULL"
                " ORDER BY deleted_at DESC, id DESC LIMIT ?",
                limit,
            )
        return [with_purge(row) for row in rows]

    def trashed(self, key: str) -> dict[str, Any] | None:
        """A page in the trash by id or slug (id, slug, title, kind, deleted_at,
        topic and purge_at), None if there is none."""
        with self.connect() as conn:
            rows = _rows(
                conn,
                f"SELECT {COLUMNS} FROM page"
                " WHERE (id = ? OR slug = ?) AND deleted_at IS NOT NULL",
                key, key,
            )  # fmt: skip
        if not rows:
            return None
        found = with_purge(rows[0])
        del found["updated_at"]
        return found

    def delete_page(self, key: str, undo: bool = False) -> None:
        """Move a page to the trash (or back); captures and files stay until a purge."""
        with self.connect() as conn:
            if undo:
                row = conn.execute(
                    "SELECT id FROM page WHERE (id = ? OR slug = ?)"
                    " AND deleted_at IS NOT NULL",
                    (key, key),
                ).fetchone()
                if row is None:
                    raise NoSuchPage(key)
                restore_in(conn, row[0])
                return
            cur = conn.execute(
                "UPDATE page SET deleted_at = ? WHERE (id = ? OR slug = ?)"
                " AND deleted_at IS NULL",
                (now(), key, key),
            )
        if cur.rowcount == 0:
            raise NoSuchPage(key)
