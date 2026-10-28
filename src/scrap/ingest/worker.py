"""The background Worker thread: claims a job, calls Claude, records the result (a
file's job is read locally instead: files.py)."""

import json
import logging
import os
import sqlite3
import threading
from collections.abc import Callable
from io import BytesIO
from typing import Any

from .. import actions, claude, claude_cli, preview, sanitise
from ..store import (
    MAX_TAGS,
    PAGE_KINDS,
    Store,
    enrich_on,
    file_enrich,
    now,
    queue_after_read,
    transaction,
)
from ..store.helpers import file_kind
from ..store.roles import IS_FIRST, UNFILED, first_capture
from . import files
from .constants import PAUSES, POLL, REV, TITLE_CAS
from .jobs import (
    charge,
    claim,
    notify,
    pause,
    put_derived,
    recover,
    resume,
    spent_today,
)

log = logging.getLogger(__name__)


Call = Callable[..., claude.Completion]


class Worker:
    """The background thread. call is claude.complete (tests pass a fake)."""

    def __init__(
        self,
        store: Store,
        call: Call | None = None,
        fetcher: Callable[[str], Any] | None = None,
    ):
        from ..enrich import Enricher  # it builds on this module

        self.store = store
        self.call = call or claude.complete
        self.budget = int(float(os.environ.get("SCRAP_BUDGET_DAY_USD", "3")) * 1e6)
        self.current: int | None = None  # the job in flight
        # Text pages (enrich/), when there is no photo to read
        self.enricher = Enricher(store, self.call, self.budget, fetcher)
        self.enrich = enrich_on()
        file_enrich()  # a bad SCRAP_FILE_ENRICH stops the start, not a file's job
        self._after_file = False  # the last job was a file's: enrich gets a turn
        self._wake, self._stop = threading.Event(), threading.Event()
        self._thread = threading.Thread(target=self.run, name="ingest", daemon=True)

    def start(self) -> None:
        with self.store.connect() as conn:
            recover(conn, now())
            with transaction(conn):
                self.enricher.recover(conn, now())
            problem = claude_cli.unavailable()  # cli without its token or binary
            if problem:
                log.error("ingest paused: %s", problem)
                with transaction(conn):
                    announce = pause(conn, None, "auth", now())
                if announce:
                    notify("auth")
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
        self.enricher.give_back()
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
        files.stop_children()  # after the give-back: a killed read then changes nothing

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
        if self._after_file:  # a file may take a minute: enrichment's turn before more
            self._after_file = False
            if self.enrich and self.enricher.step():
                return True
        with self.store.connect() as conn:
            job = claim(conn, now())
        if job is None:
            return self.enrich and self.enricher.step()
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
        with self.store.connect() as conn:
            mime = conn.execute(
                "SELECT mime FROM blob WHERE sha256 = ?", (photo,)
            ).fetchone()
        if mime is not None and file_kind(mime[0]):
            files.process(self.store, job, mime[0])  # read here: no Claude, no budget
            self._after_file = True
            return
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
        with self.store.connect() as conn:  # the text Claude's boxes may follow (rev)
            base = conn.execute(
                f"SELECT {REV} FROM capture c JOIN page p ON p.id = c.page_id"
                " WHERE c.id = ?", (cid,),
            ).fetchone()  # fmt: skip
        sent, size = self.store.put_blob(BytesIO(jpeg))
        model = claude.model_name()
        system, version = claude.prompt()
        messages = claude.photo_messages(sent, width, height)
        request = {
            "backend": claude.backend(),
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
        self.succeeded(job, run_id, done, output, (width, height), base and base[0])

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
        base_rev: int | None = None,
    ) -> None:
        """Record a reading and apply it to the page. base_rev: the page's text
        revision when the photo was sent (None: as it is now), which a list of actions
        is appended to only if the text is still at it."""
        jid, cid, photo = job["id"], job["capture_id"], job["source_sha256"]
        with self.store.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT options FROM job WHERE id = ?", (jid,)
            ).fetchone()
            if row is None:
                return  # purged while the call ran: the run went with it
            options = json.loads(row[0])  # as now: Reprocess may confirm meanwhile
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
            self._page_fields(conn, cid, photo, out, stamp, producer)
            conn.execute(
                "UPDATE job SET state = 'done', last_error = NULL, updated_at = ?"
                " WHERE id = ?",
                (stamp, jid),
            )
            queue_after_read(conn, cid)  # all read: a board's write-up, else related
            resume(conn, stamp)  # a success ends any pause
            page = conn.execute(
                f"SELECT p.id, {REV} AS rev, (SELECT sha256 FROM capture_blob WHERE"
                " capture_id = c.id ORDER BY ord LIMIT 1) AS first,"
                f" {IS_FIRST.format(c='c')} AS original"
                " FROM capture c"
                " JOIN page p ON p.id = c.page_id WHERE c.id = ?", (cid,),
            ).fetchone()  # fmt: skip
        items = [(i["text"], i["done"]) for i in out["items"]]
        if (
            page is not None
            and page["original"]  # an added photo's boxes would file the page a todo
            and page["first"] == photo
            and actions.accepted(out["intent"], out["confidence"], items)
        ):  # a Claude-authored revision of its own, once the reading is stored
            rev = page["rev"] if base_rev is None else base_rev
            actions.append(self.store, page["id"], rev, items, whiteboard=True)

    def _page_fields(
        self,
        conn: sqlite3.Connection,
        cid: str,
        photo: str,
        out: dict[str, Any],
        stamp: str,
        producer: str = "",
    ) -> None:
        """Title, tags and kind from the first photo of the page's first capture (it
        decides what the page is: photos added later only add content, #260); the
        user's win. Claude's tags join the user's on its first reading of the photo
        (tagging a photo in the composer keeps both); a later reading (Reprocess) adds
        them only to a page with none, so a tag the user took off since does not come
        back. The page keeps at most MAX_TAGS: Claude's fill what the user's leave."""
        page_id, original = first_capture(conn, cid)
        first = conn.execute(
            "SELECT sha256 FROM capture_blob WHERE capture_id = ? ORDER BY ord LIMIT 1",
            (cid,),
        ).fetchone()[0]
        if photo != first or not original:
            return
        if out["title"]:
            args = {"title": out["title"], "now": stamp, "page": page_id}
            changed = conn.execute(
                TITLE_CAS, {**args, "capture": cid, "photo": photo}
            ).rowcount
        else:
            changed = 0
        first_read = (
            conn.execute(
                "SELECT count(*) FROM derived WHERE capture_id = ?"
                " AND source_sha256 = ? AND kind = 'description'",
                (cid, photo),
            ).fetchone()[0]
            == 1  # the version just put
        )
        have = {
            r[0]
            for r in conn.execute("SELECT tag FROM tag WHERE page_id = ?", (page_id,))
        }
        if first_read or not have:  # at most MAX_TAGS in all: the user's first
            room = max(0, MAX_TAGS - len(have))
            fresh = [t for t in out["tags"] if t not in have][:room]
            changed += conn.executemany(
                "INSERT INTO tag VALUES (?, ?) ON CONFLICT DO NOTHING",
                [(page_id, tag) for tag in fresh],
            ).rowcount
            conn.executemany(  # marked as Claude's (enrich keeps them apart too)
                "INSERT INTO model_tag VALUES (?, ?, 'on', ?, ?)"
                " ON CONFLICT DO NOTHING",
                [(page_id, tag, producer, stamp) for tag in fresh],
            )
        if changed:  # a new title or tags: search sees them
            self.store.reindex(conn, page_id)
        if out["kind"] in PAGE_KINDS:
            conn.execute(
                f"UPDATE page SET kind = ? WHERE id = ? AND {UNFILED.format(p='page')}",
                (PAGE_KINDS[out["kind"]], page_id),
            )
