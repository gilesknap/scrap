"""What nightly ``scrap gc`` deletes from the database besides unused files (#276).

- **The trash.** A page trashed more than ``TRASH_DAYS`` ago is purged: its row goes,
  and with it (the schema's ``ON DELETE CASCADE``) its revisions, captures and their
  file records, Claude's results and runs, jobs, tags, search index, write-ups and
  topic memberships, all in one transaction. Its files are then unused, so gc's usual
  delete takes them, under its grace period and only after a recent backup.
- **A topic page in the trash is never purged.** Its key (``store.topics``) is the veto
  that stops discovery making the topic again, and the key's row needs its page: so
  the page stays in the trash, where the owner can still see the veto and undo it.
- **A review page** (gc's "Orphaned assets", ``orphans``) is purged like any other. The
  files it showed, in any of its revisions, that would be orphans again once it is gone
  are let go with it: their file records are taken off the capture still holding them
  (the page they went from no longer shows them), with that photo's results, jobs and
  runs, so their space is reclaimed. Without that, each would be gathered again onto a
  new review page.
- **Finished jobs.** ``job`` and ``enrich_job`` rows done or dead, last changed more
  than ``JOB_DAYS`` ago, are deleted, but the newest of each photo's ingest jobs and of
  each page's enrich jobs of a reason is kept: the PWA shows a page's or a photo's
  state from it, and a page's one first related call is known by it.

Every function here runs on an open connection; the caller owns the transaction.
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from . import orphans
from .store import body_refs
from .store.health import REVIEW
from .store.topics import IS_TOPIC
from .store.trash import MAX_DAYS, TRASH_DAYS, purge_at, trash_days

__all__ = [
    "JOB_DAYS",
    "MAX_DAYS",
    "TRASH_DAYS",
    "Purged",
    "check_days",
    "due",
    "prune_jobs",
    "purge",
    "purge_at",
    "stamp",
    "trash_days",
]

JOB_DAYS = 30.0  # finished job rows are kept this long

# The trashed pages due for a purge (:cutoff a stored timestamp): not topics
DUE = (
    "SELECT id FROM page p WHERE p.deleted_at IS NOT NULL AND p.deleted_at < :cutoff"
    f" AND NOT {IS_TOPIC.format(p='p')} ORDER BY p.deleted_at, p.id"
)
IS_REVIEW = REVIEW.format(p="p")
# The finished jobs past retention, but each photo's newest ingest job and each
# page's newest enrich job of a reason
OLD_JOBS = (
    "SELECT id FROM job WHERE state IN ('done', 'dead') AND updated_at < :cutoff"
    " AND id NOT IN (SELECT max(id) FROM job GROUP BY capture_id, source_sha256)"
)
OLD_ENRICH_JOBS = (
    "SELECT id FROM enrich_job WHERE state IN ('done', 'dead')"
    " AND updated_at < :cutoff"
    " AND id NOT IN (SELECT max(id) FROM enrich_job GROUP BY page_id, reason)"
)


def stamp(days: float) -> str:
    """The stored timestamp days ago."""
    when = datetime.now(UTC) - timedelta(days=days)
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def check_days(days: float, what: str) -> None:
    """Refuse a retention under a day (or not a number): a slip must never purge
    the trash, or the job history, of today; or over MAX_DAYS (a date that far off
    cannot be reckoned)."""
    if not days >= 1:
        raise ValueError(f"the {what} retention must be at least 1 day")
    if days > MAX_DAYS:
        raise ValueError(f"the {what} retention must be at most {MAX_DAYS} days")


@dataclass
class Purged:
    pages: int = 0  # trashed pages purged (or due, counting)
    files: int = 0  # orphaned files their review pages held, let go


def due(conn: sqlite3.Connection, cutoff: str, review: bool = True) -> list[str]:
    """The ids of the trashed pages due for a purge: trashed before cutoff (a stored
    timestamp), topics left out (see the module), and review pages unless review."""
    sql = DUE if review else DUE.replace(" ORDER BY", f" AND NOT {IS_REVIEW} ORDER BY")
    return [row[0] for row in conn.execute(sql, {"cutoff": cutoff})]


def purge(
    conn: sqlite3.Connection, cutoff: str, grace: str, review: bool = True
) -> Purged:
    """Purge the trashed pages due (see due), then let go of the files the review
    pages among them showed that are orphans now (orphans.find, with grace its
    cutoff). Without review, review pages are left for a later run. Run it inside a
    write transaction (a dry run rolls it back)."""
    ids = due(conn, cutoff, review)
    if not ids:
        return Purged()
    marks = ",".join("?" * len(ids))
    reviews = f"p.id IN ({marks}) AND {IS_REVIEW}"
    shown: set[str] = set()  # every file a review page among them ever showed
    for (body,) in conn.execute(
        f"SELECT r.body FROM page_rev r JOIN page p ON p.id = r.page_id WHERE {reviews}"
        f" UNION ALL SELECT p.body FROM page p WHERE {reviews}",
        ids + ids,
    ):
        shown |= body_refs(body)
    conn.execute(f"DELETE FROM page WHERE id IN ({marks})", ids)
    files = 0
    if shown:
        for orphan in orphans.find(conn, grace):
            if orphan.sha in shown:
                files += 1
                detach(conn, orphan.sha)
    return Purged(len(ids), files)


def detach(conn: sqlite3.Connection, sha: str) -> None:
    """Take a file off every capture holding it, with that photo's results, jobs and
    runs (an orphan: no page shows it, and none of its pages is in the trash)."""
    holders = [
        row[0]
        for row in conn.execute(
            "SELECT capture_id FROM capture_blob WHERE sha256 = ?", (sha,)
        )
    ]
    for cid in holders:
        args = (cid, sha)
        # derived first: it refers to the runs; the newest run first, as it may
        # continue an older one (parent_id)
        conn.execute(
            "DELETE FROM derived WHERE capture_id = ? AND source_sha256 = ?", args
        )
        conn.executemany(
            "DELETE FROM model_run WHERE id = ?",
            conn.execute(
                "SELECT id FROM model_run WHERE capture_id = ? AND source_sha256 = ?"
                " ORDER BY id DESC",
                args,
            ).fetchall(),
        )
        conn.execute("DELETE FROM job WHERE capture_id = ? AND source_sha256 = ?", args)
        conn.execute(
            "DELETE FROM capture_blob WHERE capture_id = ? AND sha256 = ?", args
        )


def prune_jobs(
    conn: sqlite3.Connection, cutoff: str, delete: bool = False
) -> tuple[int, int]:
    """Count (with delete, delete) the finished job and enrich_job rows past
    retention (see the module): (jobs, enrich jobs)."""
    jobs = [row[0] for row in conn.execute(OLD_JOBS, {"cutoff": cutoff})]
    texts = [row[0] for row in conn.execute(OLD_ENRICH_JOBS, {"cutoff": cutoff})]
    if delete:
        conn.executemany("DELETE FROM job WHERE id = ?", [(i,) for i in jobs])
        conn.executemany("DELETE FROM enrich_job WHERE id = ?", [(i,) for i in texts])
    return len(jobs), len(texts)
