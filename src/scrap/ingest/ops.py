"""Queue operations: reprocess, status and resume."""

import json
from typing import Any

from ..store import ENQUEUE, NotFoundError, Store, enrich_on, now, transaction
from .constants import FAR
from .jobs import enabled, resume, spent_today


def reprocess(
    store: Store, capture_id: str, photo: str | None, replace_human: bool
) -> dict[str, int]:
    """Queue a capture's photos and readable files (a PDF, a text file: read again
    locally, #234), or one of them, again: ENQUEUE. Returns how many were added
    (queued) and how many were queued or running already (already). Confirming
    replace_human reaches a job that is already queued or running too."""
    with store.connect() as conn, transaction(conn):
        found = conn.execute(
            "SELECT 1 FROM capture c JOIN page p ON p.id = c.page_id"
            " WHERE c.id = ? AND p.deleted_at IS NULL",
            (capture_id,),
        ).fetchone()
        if found is None:
            raise NotFoundError(capture_id)
        options = json.dumps({"replace_human": True} if replace_human else {})
        args = {"capture": capture_id, "photo": photo, "options": options, "now": now()}
        added = conn.execute(ENQUEUE, args).rowcount
        active = "capture_id = :capture AND coalesce(:photo, source_sha256) ="
        active += " source_sha256 AND state IN ('queued', 'running')"
        if replace_human:
            conn.execute(
                "UPDATE job SET options = json_set(options, '$.replace_human',"
                " json('true')) WHERE " + active,
                args,
            )
        count = conn.execute(f"SELECT count(*) FROM job WHERE {active}", args)
        return {"queued": added, "already": count.fetchone()[0] - added}


def status(store: Store) -> dict[str, Any]:
    """The queue: whether it is paused (and why, until when) and its jobs by state
    (photos' and files' alike: a file's job is not held by a pause)."""
    with store.connect() as conn:
        q = conn.execute("SELECT paused_until, reason FROM queue_state").fetchone()
        # Jobs of pages in the trash wait there (restoring resumes them): not counted.
        jobs = dict(
            conn.execute(
                "SELECT j.state, count(*) FROM job j"
                " JOIN capture c ON c.id = j.capture_id"
                " JOIN page p ON p.id = c.page_id WHERE p.deleted_at IS NULL"
                " GROUP BY j.state"
            )
        )
        texts = dict(
            conn.execute(
                "SELECT j.state, count(*) FROM enrich_job j JOIN page p"
                " ON p.id = j.page_id WHERE p.deleted_at IS NULL GROUP BY j.state"
            )
        )
        spent = spent_today(conn, now())
    paused = q["paused_until"] is not None and q["paused_until"] > now()
    return {
        "enabled": enabled(),
        "paused": paused,
        "reason": q["reason"] if paused else None,
        "paused_until": None if not paused or q[0] == FAR else q[0],
        "jobs": jobs,
        "enrich": {"enabled": enrich_on(), "jobs": texts},
        "spent_today_usd": spent / 1e6,
    }


def resume_queue(store: Store) -> None:
    with store.connect() as conn, transaction(conn):
        resume(conn, now())
