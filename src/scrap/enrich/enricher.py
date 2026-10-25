"""Enrich: the jobs, run by the ingest worker's thread."""

import json
import logging
import sqlite3
from typing import Any

from .. import actions, claude, fetch
from ..ingest import (
    MAX_FAILURES,
    PAUSES,
    RETRY,
    later,
    notify,
    pause,
    resume,
    spent_today,
)
from ..markdown import plain
from ..store import (
    MAX_TAGS,
    Store,
    fields_for,
    now,
    queue_related,
    topics,
    transaction,
)
from .checking import checked, record
from .constants import (
    CLAIM,
    MAX_NEW_TAGS,
    MAX_TITLE,
    SAVE_REREAD,
    SCHEMA,
    SHORT,
    TITLE_CAS,
)
from .prompts import page_images, page_message, system_prompt, vocabulary
from .relating import relate
from .synthesis import synthesise
from .types import Call, Fetch
from .writing import write_up

log = logging.getLogger(__name__)


class Enricher:
    """Enrich jobs, run by the ingest worker's thread (step) when it has no photo."""

    def __init__(self, store: Store, call: Call, budget: int, fetcher: Fetch | None):
        self.store, self.call, self.budget = store, call, budget
        self.fetch = fetcher or fetch.fetch
        self.current: int | None = None

    def claim(self) -> sqlite3.Row | None:
        with self.store.connect() as conn, transaction(conn):
            return conn.execute(CLAIM, {"now": now()}).fetchone()

    def recover(self, conn: sqlite3.Connection, stamp: str) -> None:
        """At start, in the worker's recover transaction: a running job is charged."""
        conn.execute(
            "UPDATE enrich_run SET status = 'error', error_class = 'crashed',"
            " error = 'running when the service started', finished_at = ?"
            " WHERE status = 'running'",
            (stamp,),
        )
        for (jid,) in conn.execute(
            "SELECT id FROM enrich_job WHERE state = 'running'"
        ).fetchall():
            self.charge(conn, jid, "crashed", stamp, "running when the service started")

    def give_back(self) -> None:
        """At a clean shutdown: the job in flight is queued again, for free."""
        jid = self.current
        if jid is None:
            return
        with self.store.connect() as conn, transaction(conn):
            self._requeue(conn, jid, now())
            conn.execute(
                "UPDATE enrich_run SET status = 'error', error = 'service stopped',"
                " finished_at = ? WHERE job_id = ? AND status = 'running'",
                (now(), jid),
            )

    def _requeue(self, conn: sqlite3.Connection, jid: int, stamp: str) -> None:
        """A running job back to queued, unless a newer one is queued for its page
        (a save meanwhile): then this one is done, the newer one does its work."""
        newer = conn.execute(
            "SELECT 1 FROM enrich_job q JOIN enrich_job j ON j.page_id = q.page_id"
            " WHERE j.id = ? AND q.state = 'queued'",
            (jid,),
        ).fetchone()
        state = "done" if newer else "queued"
        conn.execute(
            "UPDATE enrich_job SET state = ?, run_after = ?, updated_at = ?"
            " WHERE id = ? AND state = 'running'",
            (state, stamp, stamp, jid),
        )

    def charge(
        self, conn: sqlite3.Connection, jid: int, cls: str, stamp: str, error: str
    ) -> None:
        """A charged failure, as a photo's: retried in RETRY s (invalid output at
        once), dead at the third. A newer job queued meanwhile replaces it."""
        newer = conn.execute(
            "SELECT 1 FROM enrich_job q JOIN enrich_job j ON j.page_id = q.page_id"
            " WHERE j.id = ? AND q.state = 'queued'",
            (jid,),
        ).fetchone()
        if newer:
            conn.execute(
                "UPDATE enrich_job SET state = 'done', last_error = ?, updated_at = ?"
                " WHERE id = ?",
                (f"{cls}: {error}"[:500], stamp, jid),
            )
            return
        conn.execute(
            "UPDATE enrich_job SET failures = failures + 1, run_after = ?,"
            " last_error = ?, updated_at = ?, state = CASE WHEN failures + 1 >= ?"
            " THEN 'dead' ELSE 'queued' END WHERE id = ?",
            (stamp if cls == "invalid" else later(stamp, RETRY),
             f"{cls}: {error}"[:500], stamp, MAX_FAILURES, jid),
        )  # fmt: skip
        dead = conn.execute(
            "SELECT page_id FROM enrich_job WHERE id = ? AND state = 'dead'"
            " AND reason = 'writeup'",
            (jid,),
        ).fetchone()
        if dead is not None:  # a write-up given up on: the first related call anyway
            queue_related(conn, dead[0])

    def step(self) -> bool:
        """Claim and run one job; False if none was ready."""
        job = self.claim()
        if job is None:
            return False
        self.current = job["id"]
        try:
            self.process(job)
        except Exception as error:  # any failure of the job is charged
            log.exception("enrich job %s", job["id"])
            message = claude.redact(repr(error))[:500]
            with self.store.connect() as conn, transaction(conn):
                conn.execute(
                    "UPDATE enrich_run SET status = 'error',"
                    " error_class = 'internal', error = ?, finished_at = ?"
                    " WHERE job_id = ? AND status = 'running'",
                    (message, now(), job["id"]),
                )
                if self._running(conn, job["id"]):
                    self.charge(conn, job["id"], "internal", now(), message)
        finally:
            self.current = None
        return True

    def _running(self, conn: sqlite3.Connection, jid: int) -> bool:
        sql = "SELECT state FROM enrich_job WHERE id = ?"
        row = conn.execute(sql, (jid,)).fetchone()
        return row is not None and row[0] == "running"

    def process(self, job: sqlite3.Row) -> None:
        jid, page_id = job["id"], job["page_id"]
        with self.store.connect() as conn, transaction(conn):
            over = spent_today(conn, now()) >= self.budget
            announce = over and pause(conn, None, "budget", now())
            if over:
                self._requeue(conn, jid, now())
        if announce:
            notify("budget")
        if over:
            return
        if job["reason"] == "related":  # a page's first related call, once read
            error = relate(self.store, self.call, page_id, jid)
            if error is not None:
                self._job_failed(jid, error)
                return
            with self.store.connect() as conn, transaction(conn):
                self._done(conn, jid)
            return
        if job["reason"] == "topic":  # a topic's synthesis (#261)
            error = synthesise(self.store, self.call, page_id, jid)
            if error is not None:
                self._job_failed(jid, error)
                return
            with self.store.connect() as conn, transaction(conn):
                self._done(conn, jid)
            return
        if job["reason"] == "writeup":  # a board page's write-up (#256)
            error = write_up(self.store, self.call, page_id, jid)
            if error is not None:
                self._job_failed(jid, error)
                return
            with self.store.connect() as conn, transaction(conn):
                self._done(conn, jid)
                queue_related(conn, page_id)  # its first related call sees the write-up
            return
        with self.store.connect() as conn:
            page = conn.execute(
                "SELECT *, (SELECT max(rev) FROM page_rev WHERE page_id = page.id)"
                " AS rev FROM page WHERE id = ? AND deleted_at IS NULL",
                (page_id,),
            ).fetchone()
            if page is None:  # trashed meanwhile: nothing to do
                with transaction(conn):
                    conn.execute(
                        "UPDATE enrich_job SET state = 'done' WHERE id = ?", (jid,)
                    )
                return
            tags = [
                r[0] for r in conn.execute(
                    "SELECT tag FROM tag WHERE page_id = ?", (page_id,)
                )
            ]  # fmt: skip
            link = conn.execute(
                "SELECT url FROM capture WHERE page_id = ? AND kind = 'url'"
                " ORDER BY received_at LIMIT 1",
                (page_id,),
            ).fetchone()
            link = link and link[0]
            images = page_images(conn, page_id)
            vocab = {t for t, _ in vocabulary(conn)}
            system, version = system_prompt(conn)
        got, failed = None, None
        if link and job["reason"] == "save":
            # A text edit reads the page again without the site: the fetched text is
            # not kept, so there is nothing to reuse, and no fetch (#147)
            failed = SAVE_REREAD
        elif link:  # capture, ask and backfill fetch
            try:
                got = self.fetch(link)
            except fetch.FetchError as error:
                failed = str(error)
            except Exception as error:  # noqa: BLE001  the page is enriched anyway
                failed = f"could not fetch the page ({type(error).__name__})"
        text = plain(page["body"]).strip()
        want_summary = bool(link) or len(text) >= SHORT
        args = (page, tags, link, got, failed, want_summary)
        messages = page_message(*args, images=images)
        stored = page_message(*args, False, images)
        model, effort = claude.text_model()
        request = {
            "purpose": "enrich", "model": model, "max_tokens": claude.TEXT_MAX_TOKENS,
            "effort": effort, "system": system, "messages": stored, "schema": SCHEMA,
            "fetch": got and {"url": got.url, "chars": len(got.text)} or failed,
            "backend": claude.backend(),
        }  # fmt: skip
        with self.store.connect() as conn, transaction(conn):
            run_id = conn.execute(
                "INSERT INTO enrich_run (page_id, job_id, model, prompt_version,"
                " request, started_at) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (page_id, jid, model, version, json.dumps(request), now()),
            ).fetchone()[0]
        try:
            done = self.call(
                model, system, messages, SCHEMA, None,
                effort=effort, max_tokens=claude.TEXT_MAX_TOKENS,
            )  # fmt: skip
            try:
                out = checked(done.output, vocab, want_summary, bool(link))
            except ValueError as error:
                raise claude.CallError("invalid", str(error), completion=done) from None
        except claude.CallError as error:
            self.failed(jid, run_id, error)
            return
        if not self.succeeded(job, run_id, done, out, link, got):
            return
        items = [(i["text"], i["done"]) for i in out["items"]]
        if not link and actions.accepted(out["intent"], out["confidence"], items):
            # as the page was read: an edit since wins (a revision of Claude's own)
            actions.append(self.store, page_id, page["rev"], items)
        if job["reason"] == "ask":  # Ask Claude: a board's write-up (a topic's
            # synthesis), related pages too. A retry (related failed) does not write
            # it up again: done in this job
            with self.store.connect() as conn:
                make = synthesise if topics.is_topic(conn, page_id) else write_up
            error = (
                None
                if self._written(jid)
                else make(self.store, self.call, page_id, jid)
            ) or relate(self.store, self.call, page_id, jid)
            if error is not None:
                self._job_failed(jid, error)
                return
        with self.store.connect() as conn, transaction(conn):
            self._done(conn, jid)

    def _written(self, jid: int) -> bool:
        """Whether this job has made a write-up already (an earlier try of it)."""
        with self.store.connect() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM writeup w JOIN enrich_run r ON r.id = w.run_id"
                    " WHERE r.job_id = ?",
                    (jid,),
                ).fetchone()
                is not None
            )

    def failed(self, jid: int, run_id: int, error: claude.CallError) -> None:
        refused = error.completion is not None and (
            error.completion.stop_reason == "refusal"
        )
        status = "invalid" if error.cls == "invalid" else "error"
        status = "refused" if refused else status
        with self.store.connect() as conn, transaction(conn):
            record(conn, run_id, error.completion, status=status,
                         error_class=error.cls, error=str(error)[:500])  # fmt: skip
        self._job_failed(jid, error)

    def _job_failed(self, jid: int, error: claude.CallError) -> None:
        """A failed call's effect on its job: a pause refunds it, else it is charged."""
        announce = False
        with self.store.connect() as conn, transaction(conn):
            if not self._running(conn, jid):
                return
            if error.cls in PAUSES:
                announce = pause(conn, None, error.cls, now(), error.retry_after)
                self._requeue(conn, jid, now())
            else:
                self.charge(conn, jid, error.cls, now(), str(error))
        if announce:
            notify(error.cls)

    def _done(self, conn: sqlite3.Connection, jid: int) -> None:
        stamp = now()
        conn.execute(
            "UPDATE enrich_job SET state = 'done', last_error = NULL,"
            " updated_at = ? WHERE id = ? AND state = 'running'",
            (stamp, jid),
        )
        resume(conn, stamp)  # a success ends any pause

    def succeeded(
        self,
        job: sqlite3.Row,
        run_id: int,
        done: claude.Completion,
        out: dict[str, Any],
        link: str | None,
        got: fetch.Fetched | None,
    ) -> bool:
        """Apply what Claude added; whether the job is still this worker's (else it
        was given back at shutdown, and runs again). An Ask's job is finished by the
        caller, after its related pages."""
        jid, page_id = job["id"], job["page_id"]
        producer = done.served_model
        with self.store.connect() as conn, transaction(conn):
            record(conn, run_id, done, status="ok", output=json.dumps(out))
            if not self._running(conn, jid):
                return False  # given back at shutdown: it runs again
            stamp = now()
            alive = conn.execute(
                "SELECT kind, kind_fixed, fields FROM page"
                " WHERE id = ? AND deleted_at IS NULL",
                (page_id,),
            ).fetchone()
            if alive is not None:
                first = (
                    conn.execute(
                        "SELECT 1 FROM enrichment WHERE page_id = ?", (page_id,)
                    ).fetchone()
                    is None
                )
                self._tags(conn, page_id, out["tags"], producer, stamp,
                           first or job["reason"] != "save")  # fmt: skip
                if first and job["reason"] != "ask":  # Ask picks them itself
                    queue_related(conn, page_id)  # its first reading: related next
                source, source_title = got and got.url, got and got.title or None
                if (
                    link and job["reason"] == "save"
                ):  # not fetched: keep the last source
                    old = conn.execute(
                        "SELECT source, source_title FROM enrichment WHERE page_id = ?",
                        (page_id,),
                    ).fetchone()
                    if old is not None:
                        source, source_title = old
                conn.execute(
                    "INSERT INTO enrichment (page_id, run_id, producer, summary,"
                    " source, source_title, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (page_id) DO UPDATE SET run_id = excluded.run_id,"
                    " producer = excluded.producer, summary = excluded.summary,"
                    " source = excluded.source, source_title = excluded.source_title,"
                    " updated_at = excluded.updated_at",
                    (page_id, run_id, producer, out["summary"], source,
                     source_title, stamp),
                )  # fmt: skip
                if link:
                    title = out["title"] or (got.title if got else "")
                    if title:
                        conn.execute(
                            TITLE_CAS, {"title": title[:MAX_TITLE], "page": page_id,
                                        "url": link},
                        )  # fmt: skip
                    if alive["kind"] == "note" and not alive["kind_fixed"]:
                        fields = {**fields_for("consume", link),
                                  **json.loads(alive["fields"])}  # fmt: skip
                        conn.execute(
                            "UPDATE page SET kind = 'consume', fields = ? WHERE id = ?",
                            (json.dumps(fields), page_id),
                        )
                self.store.reindex(conn, page_id)
            elif job["reason"] == "ask":
                self._done(conn, jid)  # trashed: nothing to relate
                return False
            if job["reason"] != "ask":
                self._done(conn, jid)
            return True

    def _tags(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        tags: list[str],
        producer: str,
        stamp: str,
        add: bool,
    ) -> None:
        """Claude's tags join the page's (add: on its first reading, on Ask and for a
        new capture or backfill; a save's re-reading adds none): never one the user
        took off, at most MAX_NEW_TAGS, within MAX_TAGS in all."""
        if not add:
            return
        have = {r[0] for r in conn.execute(
            "SELECT tag FROM tag WHERE page_id = ?", (page_id,))}  # fmt: skip
        off = {r[0] for r in conn.execute(
            "SELECT tag FROM model_tag WHERE page_id = ? AND state = 'off'",
            (page_id,))}  # fmt: skip
        room = max(0, min(MAX_NEW_TAGS, MAX_TAGS - len(have)))
        fresh = [t for t in tags if t not in have and t not in off][:room]
        conn.executemany(
            "INSERT INTO tag VALUES (?, ?) ON CONFLICT DO NOTHING",
            [(page_id, t) for t in fresh],
        )
        conn.executemany(
            "INSERT INTO model_tag VALUES (?, ?, 'on', ?, ?)"
            " ON CONFLICT DO UPDATE SET state = 'on'",
            [(page_id, t, producer, stamp) for t in fresh],
        )
