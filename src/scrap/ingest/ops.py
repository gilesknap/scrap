"""Queue operations: reprocess, status, resume and the one-image trial."""

import json
import os
import time
from pathlib import Path
from typing import Any

from .. import claude, preview, sanitise
from ..store import ENQUEUE, NotFoundError, Store, enrich_on, now, transaction
from .constants import FAR
from .jobs import enabled, resume, spent_today


def reprocess(
    store: Store, capture_id: str, photo: str | None, replace_human: bool
) -> dict[str, int]:
    """Queue a capture's photos (or one of them) again. Returns how many were added
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
    """The queue: whether it is paused (and why, until when) and its jobs by state."""
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


def once(path: Path, save: Path | None = None) -> dict[str, Any]:
    """Send one image file to Claude as the worker would, outside any database, and
    describe the outcome in numbers only (no text from the image). save, if given,
    gets the full response and sanitised output, which hold everything Claude read:
    it is created (mode 600, never over an existing file) before the paid call, so
    a bad path cannot lose the result."""
    jpeg, width, height = preview.claude_jpeg(path)
    system, version = claude.prompt()
    messages = claude.photo_messages("sent", width, height)
    fd = None
    if save is not None:
        fd = os.open(save, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    model = claude.model_name()
    summary: dict[str, Any] = {
        "backend": claude.backend(),
        "model": model,
        "prompt_version": version,
        "sent": [width, height, len(jpeg)],
    }
    started = time.monotonic()
    done: claude.Completion | None = None
    try:
        done = claude.complete(
            model, system, messages, claude.SCHEMA, lambda sha: (jpeg, "image/jpeg")
        )
        out = sanitise.model_output(done.output, width, height)
        summary["outcome"] = "ok"
    except (claude.CallError, ValueError) as error:
        cls = getattr(error, "cls", "invalid")
        summary.update(outcome=cls, error=str(error))
        # a paid answer that failed the checks is still reported and saved
        done, out = getattr(error, "completion", None) or done, None
    summary["seconds"] = round(time.monotonic() - started, 1)
    if done is not None:
        summary.update(
            served_model=done.served_model,
            stop_reason=done.stop_reason,
            blocks=[b.get("type") for b in done.content],
            usage=done.usage,
            cost_usd=claude.cost_microusd(done.served_model, done.usage) / 1e6,
        )
    if out is not None:
        summary.update(
            kind=out["kind"],
            text_lines=len(out["text"].splitlines()),
            uncertain=out["text"].count("(?)"),
            tags=len(out["tags"]),
            elements_given=len(done.output.get("elements") or []) if done else 0,
            elements_kept=len(out["elements"]),
            warnings=len(out["warnings"]),
        )
    if fd is not None and save is not None:
        record = {"summary": summary, "output": out}
        if done is not None:
            record["content"] = done.content
        try:
            with os.fdopen(fd, "w") as file:
                json.dump(record, file, indent=1)
        except OSError as error:  # a full disk: keep the summary, not a stub file
            save.unlink(missing_ok=True)
            summary["save_error"] = str(error)
    return summary
