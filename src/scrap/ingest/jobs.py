"""Queue state: claiming, charging, pausing and recording derived versions."""

import json
import logging
import os
import sqlite3
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from ..store import MAX_PAGE, queue_after_read, transaction
from .constants import CLAIM, FAR, INSERT_DERIVED, MAX_FAILURES, RETRY

log = logging.getLogger(__name__)


def enabled() -> bool:
    """SCRAP_INGEST turns the worker on; it is off by default."""
    return os.environ.get("SCRAP_INGEST", "off").lower() in ("on", "1", "true", "yes")


def later(stamp: str, seconds: float) -> str:
    t = datetime.fromisoformat(stamp.replace("Z", "+00:00")) + timedelta(
        seconds=seconds
    )
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def midnight_after(stamp: str) -> str:
    day = datetime.fromisoformat(stamp.replace("Z", "+00:00")).date()
    t = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def claim(conn: sqlite3.Connection, stamp: str) -> sqlite3.Row | None:
    """Take the oldest ready job, unless the queue is paused."""
    with transaction(conn):
        return conn.execute(CLAIM, {"now": stamp}).fetchone()


def recover(conn: sqlite3.Connection, stamp: str) -> int:
    """At start: a job still running may have crashed the process, so it is charged
    (three crashes kill it rather than looping the service). Returns how many."""
    with transaction(conn):
        conn.execute(
            "UPDATE model_run SET status = 'error', error_class = 'crashed',"
            " error = 'running when the service started', finished_at = ?"
            " WHERE status = 'running'",
            (stamp,),
        )
        jobs = conn.execute("SELECT id FROM job WHERE state = 'running'").fetchall()
        for job in jobs:
            charge(conn, job[0], "crashed", stamp, "running when the service started")
    return len(jobs)


def charge(
    conn: sqlite3.Connection, job_id: int, cls: str, stamp: str, error: str
) -> None:
    """A charged failure: one more failure, retried in RETRY seconds (invalid output
    at once); the third kills the job. A dead job counts as read for the page's
    write-up and first related call (queue_after_read), so one dead photo does not
    hold them back."""
    conn.execute(
        "UPDATE job SET failures = failures + 1, run_after = ?, last_error = ?,"
        " updated_at = ?, state = CASE WHEN failures + 1 >= ? THEN 'dead'"
        " ELSE 'queued' END WHERE id = ?",
        (
            stamp if cls == "invalid" else later(stamp, RETRY),
            f"{cls}: {error}"[:500],
            stamp,
            MAX_FAILURES,
            job_id,
        ),
    )
    dead = conn.execute(
        "SELECT capture_id FROM job WHERE id = ? AND state = 'dead'", (job_id,)
    ).fetchone()
    if dead is not None:
        queue_after_read(conn, dead[0])


def pause(
    conn: sqlite3.Connection,
    job_id: int | None,
    reason: str,
    stamp: str,
    retry_after: float | None = None,
) -> bool:
    """Pause the queue and refund the job's claim: it stays queued, behind older
    jobs, with no failure added. Returns whether to announce it: the first pause
    since the last success or Resume, or one for a new reason (a budget pause that
    ran out, then a spend limit that needs Resume)."""
    q = conn.execute("SELECT outages, reason, notified_at FROM queue_state").fetchone()
    announce = q["notified_at"] is None or q["reason"] != reason
    if reason in ("credit", "auth"):
        until = FAR
    elif reason == "budget":
        until = midnight_after(stamp)
    elif retry_after is not None:
        until = later(stamp, min(retry_after, 3600))  # at most an hour
    else:
        until = later(stamp, 60 * min(2 ** q["outages"], 60))
    conn.execute(
        "UPDATE queue_state SET paused_until = ?, reason = ?, outages = outages + ?,"
        " notified_at = CASE WHEN ? THEN ? ELSE notified_at END, updated_at = ?",
        (until, reason, int(reason == "outage"), announce, stamp, stamp),
    )
    if job_id is not None:
        conn.execute(
            "UPDATE job SET state = 'queued', run_after = ?, last_error = ?,"
            " updated_at = ? WHERE id = ? AND state = 'running'",
            (stamp, reason, stamp, job_id),
        )
    return announce


def resume(conn: sqlite3.Connection, stamp: str) -> None:
    """End a pause (Resume, or a success)."""
    conn.execute(
        "UPDATE queue_state SET paused_until = NULL, reason = NULL, outages = 0,"
        " notified_at = NULL, updated_at = ?",
        (stamp,),
    )


def spent_today(conn: sqlite3.Connection, stamp: str) -> int:
    """Micro-dollars recorded for runs started since UTC midnight: photos', text
    enrichment's and topic discovery's (one budget; no topic_run before migration
    13)."""
    day = stamp[:10] + "T00:00:00.000Z"
    spent = conn.execute(
        "SELECT (SELECT coalesce(sum(cost_microusd), 0) FROM model_run"
        "  WHERE started_at >= :day)"
        " + (SELECT coalesce(sum(cost_microusd), 0) FROM enrich_run"
        "  WHERE started_at >= :day)",
        {"day": day},
    ).fetchone()[0]
    try:
        spent += conn.execute(
            "SELECT coalesce(sum(cost_microusd), 0) FROM topic_run"
            " WHERE started_at >= ?",
            (day,),
        ).fetchone()[0]
    except sqlite3.OperationalError:  # no such table: an older schema
        pass
    return spent


def put_derived(
    conn: sqlite3.Connection,
    capture_id: str,
    photo: str,
    kind: str,
    producer: str,
    stamp: str,
    *,
    run_id: int | None = None,
    author: str | None = None,
    text: str | None = None,
    data: Any = None,
    current: bool = True,
) -> sqlite3.Row:
    """Insert a version; a current one supersedes the last (a trigger), one that is
    not current is kept in the history only."""
    return conn.execute(
        INSERT_DERIVED,
        {
            "capture": capture_id,
            "photo": photo,
            "kind": kind,
            "producer": producer,
            "run": run_id,
            "author": author,
            # Within a page's most (its text is indexed with the page); a model's answer
            # is far shorter (MAX_TOKENS), so this only guards against the unexpected
            "text": text.encode()[:MAX_PAGE].decode(errors="ignore") if text else None,
            "data": None if data is None else json.dumps(data),
            "superseded": None if current else stamp,
            "now": stamp,
        },
    ).fetchone()


def notify(reason: str) -> None:
    """Announce a pause once, with fixed text naming only its reason."""
    url = os.environ.get("SCRAP_NOTIFY_URL")
    if not url:
        return
    message = f"scrap: Claude ingest paused ({reason}). Open scrap to resume."
    try:
        urllib.request.urlopen(url, message.encode(), timeout=10).close()
    except Exception:  # noqa: BLE001  a lost notice must not stop the worker
        log.warning("pause notification failed")
