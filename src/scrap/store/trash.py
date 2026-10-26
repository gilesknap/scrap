"""The trash, and when a page in it is purged (nightly ``scrap gc``, scrap.retention:
#276); every move into it or out of it is recorded (trash_revs, #332)."""

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .core import Core
from .db import _rows, transaction
from .errors import InvalidError, NoSuchPage, NoSuchRevision
from .helpers import new_ulid, now
from .roles import IS_TOPIC
from .topics import touch
from .trash_revs import RESTORE, TRASH, in_batch, record

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


WEB = "web"  # the source of a change made in the PWA or over the API
ANONYMOUS = "tagged"  # the author of a web change with no identity (uploads.author)


def trash_in(
    conn: sqlite3.Connection,
    page_id: str,
    author: str,
    source: str,
    batch: str | None = None,
    stamp: str | None = None,
) -> None:
    """Move a page to the trash, recorded as by author from source (web or mcp), in
    batch if one is given. Every way a page goes to the trash comes here."""
    stamp = stamp or now()
    conn.execute("UPDATE page SET deleted_at = ? WHERE id = ?", (stamp, page_id))
    record(conn, page_id, TRASH, author, source, batch, stamp)


def restore_in(
    conn: sqlite3.Connection,
    page_id: str,
    author: str,
    source: str,
    batch: str | None = None,
    stamp: str | None = None,
) -> None:
    """Bring a page back from the trash, recorded as trash_in records; its topics are
    due again (#261). Every way a page comes back comes here."""
    stamp = stamp or now()
    conn.execute("UPDATE page SET deleted_at = NULL WHERE id = ?", (page_id,))
    touch(conn, page_id, stamp)
    record(conn, page_id, RESTORE, author, source, batch, stamp)


def live_rows(conn: sqlite3.Connection, keys: list[str]) -> list[dict[str, Any]]:
    """The pages keys name (ids or slugs), each once, in order: NoSuchPage for a key
    that names none, InvalidError for one already in the trash."""
    found: dict[str, dict[str, Any]] = {}
    for key in keys:
        rows = _rows(
            conn, f"SELECT {COLUMNS} FROM page WHERE id = ? OR slug = ?", key, key
        )
        if not rows:
            raise NoSuchPage(key)
        if rows[0]["deleted_at"] is not None:
            raise InvalidError(f"already in the trash: {key}")
        found.setdefault(rows[0]["id"], rows[0])
    return list(found.values())


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

    def delete_page(
        self,
        key: str,
        undo: bool = False,
        author: str = ANONYMOUS,
        source: str = WEB,
    ) -> None:
        """Move a page to the trash (or back), recorded as by author from source (web
        or mcp); captures and files stay until a purge."""
        with self.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT id FROM page WHERE (id = ? OR slug = ?)"
                " AND (deleted_at IS NOT NULL) = ?",
                (key, key, undo),
            ).fetchone()
            if row is None:
                raise NoSuchPage(key)
            (restore_in if undo else trash_in)(conn, row[0], author, source)

    def trash_pages(
        self, keys: list[str], author: str, source: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """Move pages to the trash (ids or slugs; a page named twice counts once), as
        delete_page does each, all or nothing: refused, moving none, if a key names no
        page (NoSuchPage) or one already in the trash (InvalidError). Several pages
        share a batch id, returned, which restore_batch brings back at once. Returns
        {batch, pages}: each page's id, slug, title, kind, topic, deleted_at and
        purge_at (as the trash lists it; null in a dry run, which moves nothing)."""
        with self.connect() as conn, transaction(conn):
            rows = live_rows(conn, keys)
            stamp = None if dry_run else now()
            batch = new_ulid() if len(rows) > 1 and not dry_run else None
            for row in rows:
                if stamp is not None:
                    trash_in(conn, row["id"], author, source, batch, stamp)
                row["deleted_at"] = stamp
                del row["updated_at"]
        return {"batch": batch, "pages": [with_purge(row) for row in rows]}

    def restore_batch(
        self, batch: str, author: str, source: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """Bring back from the trash every page a batch (trash_pages') moved there and
        that is still there from it; the rest (brought back since, or moved there again
        by a later call) are skipped, by id; one purged since is in neither (its
        records went with it). Each restore is recorded with the batch.
        NoSuchRevision if no page that call moved is left (or it never was). Returns
        {batch, pages, skipped}: the pages as trashed gives them (before the restore),
        skipped their ids. dry_run: restore nothing."""
        with self.connect() as conn, transaction(conn):
            there, skipped = in_batch(conn, batch)
            if not there and not skipped:
                raise NoSuchRevision(f"batch {batch}")
            pages = [
                with_purge(_rows(
                    conn, f"SELECT {COLUMNS} FROM page WHERE id = ?", page_id
                )[0])
                for page_id in there
            ]  # fmt: skip
            if not dry_run:
                stamp = now()
                for page_id in there:
                    restore_in(conn, page_id, author, source, batch, stamp)
        for page in pages:
            del page["updated_at"]
        return {"batch": batch, "pages": pages, "skipped": skipped}

    def is_trash_batch(self, batch: str) -> bool:
        """Whether batch is one a call moved pages to the trash as (trash_pages')."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM page_trash_rev WHERE batch_id = ?"
                " AND action = ?)",
                (batch, TRASH),
            ).fetchone()
        return row[0] == 1
