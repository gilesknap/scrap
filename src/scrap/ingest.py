"""The ingest queue and its worker: each photo goes to Claude once, in the background.

One daemon thread in the service claims one job at a time, calls Claude holding no lock,
then records the run and its results in one transaction. Outages and spending problems
pause the whole queue and refund the claim; every other failure is charged to the job,
and its third kills it. See docs/explanations/ingest.md.
"""

import json
import logging
import os
import sqlite3
import threading
import time
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

from . import claude, preview, sanitise
from .store import ENQUEUE, NotFoundError, Store, now, transaction

__all__ = ["Worker", "claim", "enabled", "pause", "recover", "resume", "charge"]

log = logging.getLogger(__name__)

FAR = "9999-12-31T00:00:00.000Z"  # paused until Resume
MAX_FAILURES = 3
RETRY = 600  # seconds after a charged failure (invalid output: at once)
POLL = 30  # seconds the idle worker sleeps unless woken
PAUSES = ("credit", "auth", "outage", "budget")
PAGE_KINDS = {
    "whiteboard": "whiteboard",
    "diagram": "whiteboard",
    "document": "document",
}

CLAIM = """
UPDATE job SET state = 'running', updated_at = :now
WHERE id = (
    SELECT j.id FROM job j
    JOIN capture c ON c.id = j.capture_id
    JOIN page p ON p.id = c.page_id
    WHERE j.state = 'queued' AND j.run_after <= :now AND p.deleted_at IS NULL
    ORDER BY j.run_after, j.id LIMIT 1)
  AND NOT EXISTS (SELECT 1 FROM queue_state WHERE paused_until > :now)
RETURNING id, capture_id, source_sha256, failures, options
"""
TITLE_CAS = """
UPDATE page SET title = :title, updated_at = :now
WHERE id = :page AND deleted_at IS NULL
  AND title = (SELECT title FROM page_rev WHERE page_id = :page AND rev = 1)
  AND NOT EXISTS (SELECT 1 FROM page_rev WHERE page_id = :page AND rev > 1)
  AND EXISTS (SELECT 1 FROM capture c WHERE c.id = :capture AND c.page_id = :page
              AND c.text IS NULL
              AND :photo = (SELECT sha256 FROM capture_blob
                            WHERE capture_id = c.id ORDER BY ord LIMIT 1))
"""
INSERT_DERIVED = """
INSERT INTO derived (capture_id, source_sha256, kind, version, producer, run_id, author,
                     text, data, superseded_at, created_at)
VALUES (:capture, :photo, :kind, (SELECT coalesce(max(version), 0) + 1 FROM derived
                                  WHERE capture_id = :capture AND source_sha256 = :photo
                                    AND kind = :kind),
        :producer, :run, :author, :text, :data, :superseded, :now)
RETURNING id, version
"""


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
    at once); the third kills the job."""
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
    """Micro-dollars recorded for runs started since UTC midnight."""
    return conn.execute(
        "SELECT coalesce(sum(cost_microusd), 0) FROM model_run WHERE started_at >= ?",
        (stamp[:10] + "T00:00:00.000Z",),
    ).fetchone()[0]


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
            "text": text or None,
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


Call = Callable[..., claude.Completion]


class Worker:
    """The background thread. call is claude.complete (tests pass a fake)."""

    def __init__(self, store: Store, call: Call | None = None):
        self.store = store
        self.call = call or claude.complete
        self.budget = int(float(os.environ.get("SCRAP_BUDGET_DAY_USD", "3")) * 1e6)
        self.current: int | None = None  # the job in flight
        self._wake, self._stop = threading.Event(), threading.Event()
        self._thread = threading.Thread(target=self.run, name="ingest", daemon=True)

    def start(self) -> None:
        with self.store.connect() as conn:
            recover(conn, now())
        self._thread.start()

    def alive(self) -> bool:
        return self._thread.is_alive()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        """At a clean shutdown: stop claiming and give the job in flight back for
        free (its call is abandoned)."""
        self._stop.set()
        self._wake.set()
        job = self.current
        if job is not None:
            with self.store.connect() as conn, transaction(conn):
                conn.execute(
                    "UPDATE job SET state = 'queued', updated_at = ?"
                    " WHERE id = ? AND state = 'running'",
                    (now(), job),
                )
                conn.execute(
                    "UPDATE model_run SET status = 'error', error = 'service stopped',"
                    " finished_at = ? WHERE job_id = ? AND status = 'running'",
                    (now(), job),
                )

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                busy = self.step()
            except Exception:  # the loop itself must never die
                log.exception("ingest worker")
                busy = False
            if not busy:
                self._wake.wait(POLL)
                self._wake.clear()

    def step(self) -> bool:
        """Claim and process one job; False if there was none to claim."""
        with self.store.connect() as conn:
            job = claim(conn, now())
        if job is None:
            return False
        self.current = job["id"]
        try:
            self.process(job)
        except Exception as error:  # any failure of the job is charged
            log.exception("ingest job %s", job["id"])
            with self.store.connect() as conn, transaction(conn):
                conn.execute(
                    "UPDATE model_run SET status = 'error', error_class = 'internal',"
                    " error = ?, finished_at = ?"
                    " WHERE job_id = ? AND status = 'running'",
                    (claude.redact(repr(error))[:500], now(), job["id"]),
                )
                if self._running(conn, job["id"]):
                    charge(
                        conn, job["id"], "internal", now(), claude.redact(repr(error))
                    )
        finally:
            self.current = None
        return True

    def _running(self, conn: sqlite3.Connection, job_id: int) -> bool:
        row = conn.execute("SELECT state FROM job WHERE id = ?", (job_id,)).fetchone()
        return row is not None and row[0] == "running"

    def _blob(self, sha: str) -> tuple[bytes, str]:
        path, mime = self.store.blob(sha)
        return path.read_bytes(), mime

    def process(self, job: sqlite3.Row) -> None:
        jid, cid, photo = job["id"], job["capture_id"], job["source_sha256"]
        with self.store.connect() as conn, transaction(conn):
            over = spent_today(conn, now()) >= self.budget
            announce = over and pause(conn, jid, "budget", now())
        if announce:
            notify("budget")
        if over:
            return
        try:
            jpeg, width, height = preview.for_claude(self.store, photo)
        except Exception as error:  # decode or HEIC failure, too large
            with self.store.connect() as conn, transaction(conn):
                charge(conn, jid, "image", now(), str(error))
            return
        sent, size = self.store.put_blob(BytesIO(jpeg))
        model = claude.model_name()
        system, version = claude.prompt()
        messages = claude.photo_messages(sent, width, height)
        request = {
            "model": model,
            "max_tokens": claude.MAX_TOKENS,
            "effort": claude.EFFORT,
            "system": system,
            "messages": messages,
            "schema": claude.SCHEMA,
        }
        with self.store.connect() as conn, transaction(conn):
            conn.execute(
                "INSERT INTO blob VALUES (?, 'image/jpeg', ?, ?)"
                " ON CONFLICT DO NOTHING",
                (sent, size, now()),
            )
            run_id = conn.execute(
                "INSERT INTO model_run (capture_id, source_sha256, job_id, purpose,"
                " model, prompt_version, sent_sha256, image_width, image_height,"
                " request, started_at) VALUES (?, ?, ?, 'ingest', ?, ?, ?, ?, ?, ?, ?)"
                " RETURNING id",
                (cid, photo, jid, model, version, sent, width, height,
                 json.dumps(request), now()),
            ).fetchone()[0]  # fmt: skip
        try:
            done = self.call(model, system, messages, claude.SCHEMA, self._blob)
            try:
                output = sanitise.model_output(done.output, width, height)
            except ValueError as error:
                raise claude.CallError("invalid", str(error), completion=done) from None
        except claude.CallError as error:
            self.failed(job, run_id, error)
            return
        self.succeeded(job, run_id, done, output, (width, height))

    def _record(
        self,
        conn: sqlite3.Connection,
        run_id: int,
        done: claude.Completion | None,
        **fields: Any,
    ) -> None:
        if done is not None:
            fields.update(
                served_model=done.served_model,
                response=json.dumps(
                    {"content": done.content, "stop_reason": done.stop_reason}
                ),
                usage=json.dumps(done.usage),
                cost_microusd=claude.cost_microusd(done.served_model, done.usage),
            )
        fields["finished_at"] = now()
        names = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE model_run SET {names} WHERE id = ?", (*fields.values(), run_id)
        )

    def failed(self, job: sqlite3.Row, run_id: int, error: claude.CallError) -> None:
        refused = error.completion is not None and (
            error.completion.stop_reason == "refusal"
        )
        status = (
            "refused" if refused else "invalid" if error.cls == "invalid" else "error"
        )
        announce = False
        with self.store.connect() as conn, transaction(conn):
            self._record(
                conn,
                run_id,
                error.completion,
                status=status,
                error_class=error.cls,
                error=str(error)[:500],
            )
            if not self._running(conn, job["id"]):
                return  # purged, or given back at shutdown
            if error.cls in PAUSES:
                announce = pause(conn, job["id"], error.cls, now(), error.retry_after)
            else:
                charge(conn, job["id"], error.cls, now(), str(error))
        if announce:
            notify(error.cls)

    def succeeded(
        self,
        job: sqlite3.Row,
        run_id: int,
        done: claude.Completion,
        out: dict[str, Any],
        size: tuple[int, int],
    ) -> None:
        jid, cid, photo = job["id"], job["capture_id"], job["source_sha256"]
        options = json.loads(job["options"])
        with self.store.connect() as conn, transaction(conn):
            if (
                conn.execute("SELECT 1 FROM job WHERE id = ?", (jid,)).fetchone()
                is None
            ):
                return  # purged while the call ran: the run went with it
            self._record(conn, run_id, done, status="ok", output=json.dumps(out))
            if not self._running(conn, jid):
                return  # given back at shutdown: it runs again
            stamp, producer = now(), done.served_model
            put_derived(
                conn, cid, photo, "ocr", producer, stamp, run_id=run_id,
                text=out["text"],
            )  # fmt: skip
            put_derived(
                conn, cid, photo, "description", producer, stamp, run_id=run_id,
                text=out["description"], data={"kind": out["kind"]},
            )  # fmt: skip
            if out["elements"]:
                drawing = conn.execute(
                    "SELECT producer FROM derived WHERE capture_id = ?"
                    " AND source_sha256 = ? AND kind = 'excalidraw'"
                    " AND superseded_at IS NULL",
                    (cid, photo),
                ).fetchone()
                human = drawing is not None and drawing[0] == "human"
                data = {
                    "format": "skeleton",
                    "width": size[0],
                    "height": size[1],
                    "elements": out["elements"],
                }
                put_derived(
                    conn, cid, photo, "excalidraw", producer, stamp, run_id=run_id,
                    data=data, current=not human or bool(options.get("replace_human")),
                )  # fmt: skip
            self._page_fields(conn, cid, photo, out, stamp)
            conn.execute(
                "UPDATE job SET state = 'done', last_error = NULL, updated_at = ?"
                " WHERE id = ?",
                (stamp, jid),
            )
            resume(conn, stamp)  # a success ends any pause

    def _page_fields(
        self,
        conn: sqlite3.Connection,
        cid: str,
        photo: str,
        out: dict[str, Any],
        stamp: str,
    ) -> None:
        """Title, tags and kind from a capture's first photo; the user's win."""
        page_id = conn.execute(
            "SELECT page_id FROM capture WHERE id = ?", (cid,)
        ).fetchone()[0]
        first = conn.execute(
            "SELECT sha256 FROM capture_blob WHERE capture_id = ? ORDER BY ord LIMIT 1",
            (cid,),
        ).fetchone()[0]
        if photo != first:
            return
        if out["title"]:
            args = {"title": out["title"], "now": stamp, "page": page_id}
            changed = conn.execute(
                TITLE_CAS, {**args, "capture": cid, "photo": photo}
            ).rowcount
            if changed:
                self.store.reindex(conn, page_id)
        if not conn.execute(
            "SELECT 1 FROM tag WHERE page_id = ?", (page_id,)
        ).fetchone():
            conn.executemany(
                "INSERT INTO tag VALUES (?, ?) ON CONFLICT DO NOTHING",
                [(page_id, tag) for tag in out["tags"]],
            )
        if out["kind"] in PAGE_KINDS:
            conn.execute(
                "UPDATE page SET kind = ? WHERE id = ? AND kind = 'note'"
                " AND kind_fixed = 0",
                (PAGE_KINDS[out["kind"]], page_id),
            )


def reprocess(
    store: Store, capture_id: str, photo: str | None, replace_human: bool
) -> int:
    """Queue a capture's photos (or one of them) again; returns how many were added
    (none if they are queued already)."""
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
        return conn.execute(ENQUEUE, args).rowcount


def status(store: Store) -> dict[str, Any]:
    """The queue: whether it is paused (and why, until when) and its jobs by state."""
    with store.connect() as conn:
        q = conn.execute("SELECT paused_until, reason FROM queue_state").fetchone()
        jobs = dict(conn.execute("SELECT state, count(*) FROM job GROUP BY state"))
        spent = spent_today(conn, now())
    paused = q["paused_until"] is not None and q["paused_until"] > now()
    return {
        "enabled": enabled(),
        "paused": paused,
        "reason": q["reason"] if paused else None,
        "paused_until": None if not paused or q[0] == FAR else q[0],
        "jobs": jobs,
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
