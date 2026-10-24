"""Enrich: Claude reads a text page and adds tags and a summary; related pages (#85).

A page's text is the user's and is never edited. On capture, save, backfill or Ask,
one tool-less, schema-checked call per page, on a small model (claude.text_model()),
gives tags (preferring the vocabulary in use), a summary, and for a saved link a
title; a link is fetched first (fetch.py: public addresses only, size and time
limits). Related pages are a call of their own (relate): on Ask, and in the nightly
pass (related_pass, scrap enrich --related) for every page changed since its last
picks, from candidates found by shared tags and full-text search, so the library's
size does not matter. What it adds is kept apart from the text (enrichment,
model_tag, related) and the user wins: a tag the user took off never comes back,
their tags are never removed, a title is replaced only while it is still the link as
captured, the kind only while it is an unfixed note. Jobs run on the ingest worker's
thread; everything shares its queue pause and daily budget. See
docs/explanations/ingest.md.
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import unicodedata
from collections.abc import Callable
from typing import Any

from . import actions, claude, fetch
from .ingest import (
    MAX_FAILURES,
    PAUSES,
    RETRY,
    later,
    notify,
    pause,
    resume,
    spent_today,
)
from .markdown import plain
from .query import CONTROL
from .store import (
    ENRICH_KINDS,
    MAX_TAG,
    MAX_TAGS,
    NOT_BY_INGEST,
    Store,
    fields_for,
    model_summary,
    now,
    queue_enrich,
    transaction,
    unlink,
)

__all__ = [
    "Enricher", "SCHEMA", "RELATED_SCHEMA", "backfill", "ask", "candidates", "relate",
    "related_pass",
]  # fmt: skip

log = logging.getLogger(__name__)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tags", "summary", "title", *claude.INTENT_PROPERTIES],
    "properties": {
        **claude.INTENT_PROPERTIES,
        "tags": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "title": {"type": "string"},
    },
}
# Related pages: a call of its own (the nightly pass, and Ask Claude), not on every save
RELATED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["related"],
    "properties": {"related": {"type": "array", "items": {"type": "integer"}}},
}
SHORT = 200  # characters: a shorter note gets tags but no summary
MAX_BODY = 12_000  # characters of the page's text sent
MAX_NEW_TAGS = 5  # Claude's tags added to a page at most
MAX_INVENTED = 2  # of which at most this many not already in use
MAX_RELATED = 5
MAX_SUMMARY = 600
MAX_TITLE = 200
MAX_VOCAB = 600  # tags listed, most used first
MAX_CANDIDATES = 150  # pages in a related call's index (~40 tokens each)
BY_TAGS, BY_WORDS = 90, 60  # of which, at most, sharing tags and matching words
WORD = re.compile(r"[^\W_]{4,}")  # a word worth matching: 4 letters or more

CLAIM = """
UPDATE enrich_job SET state = 'running', updated_at = :now
WHERE id = (
    SELECT j.id FROM enrich_job j JOIN page p ON p.id = j.page_id
    WHERE j.state = 'queued' AND j.run_after <= :now AND p.deleted_at IS NULL
      AND NOT EXISTS (SELECT 1 FROM enrich_job r
                      WHERE r.page_id = j.page_id AND r.state = 'running')
    ORDER BY j.run_after, j.id LIMIT 1)
  AND NOT EXISTS (SELECT 1 FROM queue_state WHERE paused_until > :now)
RETURNING id, page_id, reason, failures
"""
# A saved link's title, while it is still the link as captured (no edit since)
TITLE_CAS = """
UPDATE page SET title = :title
WHERE id = :page AND deleted_at IS NULL
  AND title = (SELECT title FROM page_rev WHERE page_id = :page AND rev = 1)
  AND title = :url
  AND NOT EXISTS (SELECT 1 FROM page_rev WHERE page_id = :page AND rev > 1)
"""


def candidates(
    conn: sqlite3.Connection, page_id: str, limit: int = MAX_CANDIDATES
) -> list[dict[str, Any]]:
    """The pages Claude may pick as related to a page, at most limit whatever the
    library's size: those sharing the most tags with it (BY_TAGS), then those whose
    title, tags, summary or text best match the words of its title, tags and summary
    (full-text search, BY_WORDS), then the most recently changed; none in the trash.
    Swappable (CANDIDATES): embeddings (#53) if these prove too weak."""
    me = conn.execute(
        "SELECT p.title, p.fields, coalesce(e.summary, '') FROM page p"
        " LEFT JOIN enrichment e ON e.page_id = p.id WHERE p.id = ?",
        (page_id,),
    ).fetchone()
    ids: dict[str, None] = {}
    alive = "p.deleted_at IS NULL AND p.id <> :id"
    for (other,) in conn.execute(
        "SELECT b.page_id FROM tag a JOIN tag b ON a.tag = b.tag"
        f" JOIN page p ON p.id = b.page_id WHERE a.page_id = :id AND {alive}"
        " GROUP BY b.page_id ORDER BY count(*) DESC, max(p.updated_at) DESC"
        " LIMIT :n",
        {"id": page_id, "n": BY_TAGS},
    ):
        ids[other] = None
    if me is not None:
        human = json.loads(me[1]).get("summary")
        tags = " ".join(r[0] for r in conn.execute(
            "SELECT tag FROM tag WHERE page_id = ?", (page_id,)))  # fmt: skip
        about = human if isinstance(human, str) else me[2]
        words = dict.fromkeys(
            w.lower() for w in WORD.findall(f"{me[0]} {tags} {about}")
        )
        query = " OR ".join(f'"{w}"' for w in list(words)[:24])
        if query:
            n = 0
            for (other,) in conn.execute(
                "SELECT c.page_id FROM chunk_fts JOIN chunk c ON c.id = chunk_fts.rowid"
                f" JOIN page p ON p.id = c.page_id WHERE chunk_fts MATCH :q AND {alive}"
                " ORDER BY bm25(chunk_fts) LIMIT :n",
                {"q": query, "id": page_id, "n": BY_WORDS * 3},
            ):
                if other not in ids:
                    ids[other] = None
                    n += 1
                    if n >= BY_WORDS:
                        break
    for (other,) in conn.execute(
        f"SELECT p.id FROM page p WHERE {alive} ORDER BY p.updated_at DESC LIMIT :n",
        {"id": page_id, "n": limit},
    ):
        if len(ids) >= limit:
            break
        ids.setdefault(other, None)
    order = list(ids)[:limit]
    rows = {
        r["id"]: r
        for r in conn.execute(
            "SELECT p.id, p.title, p.fields, coalesce(e.summary, '') AS summary,"
            " (SELECT group_concat(tag, '\x1f') FROM tag WHERE page_id = p.id) AS tags"
            " FROM page p LEFT JOIN enrichment e ON e.page_id = p.id"
            " WHERE p.id IN (SELECT value FROM json_each(?))",
            (json.dumps(order),),
        )
    }
    out = []
    for other in order:
        r = rows[other]
        human = json.loads(r["fields"]).get("summary")
        out.append({
            "id": r["id"],
            "title": r["title"],
            "tags": r["tags"].split("\x1f") if r["tags"] else [],
            "summary": human if isinstance(human, str) else r["summary"],
        })  # fmt: skip
    return out


CANDIDATES: Callable[[sqlite3.Connection, str], list[dict[str, Any]]] = candidates


def vocabulary(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """The tags in use (on pages not in the trash), most used first."""
    return [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT t.tag, count(*) FROM tag t JOIN page p ON p.id = t.page_id"
            " WHERE p.deleted_at IS NULL GROUP BY t.tag"
            " ORDER BY count(*) DESC, t.tag LIMIT ?",
            (MAX_VOCAB,),
        )
    ]


def one_line(text: str, most: int) -> str:
    text = " ".join(CONTROL.sub(" ", text).split())
    return text if len(text) <= most else text[: most - 1] + "…"


def index_lines(pages: list[dict[str, Any]]) -> str:
    """The compact index: one line a page, about 40 tokens."""
    lines = []
    for n, p in enumerate(pages, start=1):
        tags = " ".join(f"#{t}" for t in p["tags"][:6])
        about = one_line(p["summary"] or "", 150)
        parts = [f"{n}. {one_line(unlink(p['title']), 100)}", tags, about]
        lines.append(" | ".join(x for x in parts if x))
    return "\n".join(lines)


def system_prompt(conn: sqlite3.Connection) -> tuple[str, str]:
    """The fixed prompt, then the tags in use; and the prompt's version (of the fixed
    part and the schema)."""
    text, version = claude.prompt("enrich", SCHEMA)
    vocab = ", ".join(f"{t} ({n})" for t, n in vocabulary(conn)) or "(none yet)"
    return f"{text}\n## Tags in use\n\n{vocab}\n", version


def related_prompt(pages: list[dict[str, Any]]) -> tuple[str, str]:
    """The related call's fixed prompt, then the index of candidate pages."""
    text, version = claude.prompt("related", RELATED_SCHEMA)
    return f"{text}\n## Other pages\n\n{index_lines(pages) or '(none)'}\n", version


def related_message(page: sqlite3.Row, tags: list[str], summary: str) -> list[dict]:
    """The related call's user turn: the page in brief."""
    text = "\n".join([
        f"Kind: {page['kind']}",
        f"Title: {page['title']}",
        f"Tags: {', '.join(tags) or '(none)'}",
        f"Summary: {summary or '(none)'}",
        "Start of its text:",
        "<page>",
        plain(page["body"]).strip()[:2000] or "(empty)",
        "</page>",
    ])  # fmt: skip
    return [{"role": "user", "content": [{"type": "text", "text": text}]}]


# The run's fetch field for a save's re-reading of a link page: skipped, not failed
SAVE_REREAD = "skipped: save re-read"


def page_message(
    page: sqlite3.Row,
    tags: list[str],
    link: str | None,
    got: fetch.Fetched | None,
    failed: str | None,
    want_summary: bool,
    keep_text: bool = True,
) -> list[dict[str, Any]]:
    """The user turn: the page (title, kind, tags, its text) and for a link what was
    fetched. keep_text False puts a placeholder for the fetched text (as stored: a read
    keeps its link and summary only)."""
    body = plain(page["body"]).strip()[:MAX_BODY]
    parts = [
        f"Kind: {page['kind']}",
        f"Its tags: {', '.join(tags) or '(none)'}",
        f"Title: {page['title']}",
        "Text:",
        "<page>",
        body or "(empty)",
        "</page>",
    ]
    if link:
        parts += ["", f"This page is a saved link: {link}"]
        if got is not None:
            text = got.text
            if not keep_text:
                digest = hashlib.sha256(text.encode()).hexdigest()[:16]
                text = f"[fetched text: {len(text)} characters, sha256 {digest}]"
            parts += [
                f"Fetched from: {got.url}",
                f"Its title: {got.title or '(none)'}",
                f"Its description: {got.description or '(none)'}",
                "<fetched>",
                text or "(no readable text)",
                "</fetched>",
            ]
        else:
            if failed == SAVE_REREAD:
                parts.append(
                    "The link was not fetched again; summarise from the page text"
                    " and address."
                )
            else:
                parts.append(f"It could not be fetched: {failed}")
    parts += ["", "Write a summary." if want_summary else "No summary is wanted."]
    return [{"role": "user", "content": [{"type": "text", "text": "\n".join(parts)}]}]


def clean_tag(tag: Any) -> str | None:
    if not isinstance(tag, str):
        return None
    new = " ".join(CONTROL.sub(" ", tag).split()).lstrip("#").lower().strip()
    new = unicodedata.normalize("NFC", new)
    return new if 0 < len(new) <= min(MAX_TAG, 40) else None


def checked(
    out: dict[str, Any], vocab: set[str], want_summary: bool, link: bool
) -> dict[str, Any]:
    """The model's output within bounds (ValueError if not an answer at all)."""
    if not all(k in out for k in ("tags", "summary", "title")):
        raise ValueError("output lacks a field")
    tags: list[str] = []
    invented = 0
    for raw in out["tags"] if isinstance(out["tags"], list) else []:
        tag = clean_tag(raw)
        if tag is None or tag in tags:
            continue
        if tag not in vocab:
            if invented >= MAX_INVENTED:
                continue
            invented += 1
        tags.append(tag)
    summary = out["summary"] if isinstance(out["summary"], str) else ""
    summary = " ".join(CONTROL.sub(" ", summary).split())[:MAX_SUMMARY]
    title = out["title"] if isinstance(out["title"], str) else ""
    title = " ".join(CONTROL.sub(" ", title).split())[:MAX_TITLE] if link else ""
    intent, confidence = actions.clean_intent(out)
    items = actions.clean_items(out.get("items")) if intent == actions.INTENT else []
    return {
        "tags": tags[: MAX_NEW_TAGS * 2],
        "summary": summary if want_summary else "",
        "title": title,
        "intent": intent,
        "confidence": confidence,
        "items": [{"text": t, "done": d} for t, d in items],
    }


def checked_related(out: dict[str, Any], n_candidates: int) -> list[int]:
    """Up to MAX_RELATED distinct, valid index numbers (ValueError if no answer)."""
    if not isinstance(out.get("related"), list):
        raise ValueError("output lacks related")
    related: list[int] = []
    for n in out["related"]:
        if type(n) is int and 1 <= n <= n_candidates and n not in related:
            related.append(n)
    return related[:MAX_RELATED]


def record(
    conn: sqlite3.Connection,
    run_id: int,
    done: claude.Completion | None,
    **fields: Any,
) -> None:
    """Finish an enrich_run row: its outcome, and the response, usage and cost."""
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
        f"UPDATE enrich_run SET {names} WHERE id = ?", (*fields.values(), run_id)
    )


Call = Callable[..., claude.Completion]
Fetch = Callable[[str], fetch.Fetched]


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
        messages = page_message(page, tags, link, got, failed, want_summary)
        stored = page_message(page, tags, link, got, failed, want_summary, False)
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
        if job["reason"] == "ask":  # Ask Claude: its related pages too, now
            error = relate(self.store, self.call, page_id, jid)
            if error is not None:
                self._job_failed(jid, error)
                return
        with self.store.connect() as conn, transaction(conn):
            self._done(conn, jid)

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


def ask(store: Store, key: str) -> dict[str, Any]:
    """Queue a page for Claude now (the page's Ask Claude); the page as it is then."""
    with store.connect() as conn, transaction(conn):
        page = store._page_row(conn, key)  # noqa: SLF001  one transaction
        queue_enrich(conn, page["id"], "ask")
        return store.page_in(conn, page["id"])


def backfill(store: Store, limit: int | None = None, dry_run: bool = False) -> int:
    """Queue every note, todo, read or link with no tags that Claude has not read (not
    in the trash, and not a photo, whiteboard or document page, nor one with a photo or
    file), oldest first: a one-off command. Returns how many (would be) queued."""
    with store.connect() as conn, transaction(conn):
        ids = [r[0] for r in conn.execute(
            "SELECT p.id FROM page p WHERE p.deleted_at IS NULL"
            f" AND p.kind IN ({','.join('?' * len(ENRICH_KINDS))})"
            " AND NOT EXISTS (SELECT 1 FROM tag t WHERE t.page_id = p.id)"
            f" AND {NOT_BY_INGEST.format(p='p')}"
            " AND NOT EXISTS (SELECT 1 FROM enrichment e WHERE e.page_id = p.id)"
            " ORDER BY p.created_at LIMIT ?",
            (*ENRICH_KINDS, -1 if limit is None else limit),
        )]  # fmt: skip
        if not dry_run:
            for page_id in ids:
                queue_enrich(conn, page_id, "backfill")
    return len(ids)


def relate(
    store: Store, call: Call, page_id: str, job_id: int | None = None
) -> claude.CallError | None:
    """One related call for a page: Claude picks from its candidates (CANDIDATES) and
    the picks replace its related rows. The run is recorded either way; a failure is
    returned for the caller to act on (pause, charge or carry on). None: done, or the
    page is in the trash. Related shows both ways: a page picked is shown the picker."""
    with store.connect() as conn:
        page = conn.execute(
            "SELECT * FROM page WHERE id = ? AND deleted_at IS NULL", (page_id,)
        ).fetchone()
        if page is None:
            return None
        tags = [r[0] for r in conn.execute(
            "SELECT tag FROM tag WHERE page_id = ?", (page_id,))]  # fmt: skip
        human = json.loads(page["fields"]).get("summary")
        summary = human if isinstance(human, str) else model_summary(conn, page_id)
        pages = CANDIDATES(conn, page_id)
    system, version = related_prompt(pages)
    messages = related_message(page, tags, summary)
    model, effort = claude.text_model()
    request = {
        "purpose": "related", "model": model, "max_tokens": claude.TEXT_MAX_TOKENS,
        "effort": effort, "system": system, "messages": messages,
        "schema": RELATED_SCHEMA, "candidates": [p["id"] for p in pages],
        "backend": claude.backend(),
    }  # fmt: skip
    with store.connect() as conn, transaction(conn):
        run_id = conn.execute(
            "INSERT INTO enrich_run (page_id, job_id, model, prompt_version, request,"
            " started_at) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (page_id, job_id, model, version, json.dumps(request), now()),
        ).fetchone()[0]
    try:
        done = call(
            model, system, messages, RELATED_SCHEMA, None,
            effort=effort, max_tokens=claude.TEXT_MAX_TOKENS,
        )  # fmt: skip
        try:
            picks = checked_related(done.output, len(pages))
        except ValueError as error:
            raise claude.CallError("invalid", str(error), completion=done) from None
    except claude.CallError as error:
        refused = error.completion is not None and (
            error.completion.stop_reason == "refusal"
        )
        status = (
            "refused" if refused else ("invalid" if error.cls == "invalid" else "error")
        )
        with store.connect() as conn, transaction(conn):
            record(conn, run_id, error.completion, status=status,
                   error_class=error.cls, error=str(error)[:500])  # fmt: skip
        return error
    with store.connect() as conn, transaction(conn):
        record(conn, run_id, done, status="ok", output=json.dumps({"related": picks}))
        conn.execute("DELETE FROM related WHERE page_id = ?", (page_id,))
        conn.executemany(
            "INSERT INTO related SELECT ?, ?, ? WHERE EXISTS"
            " (SELECT 1 FROM page WHERE id = ? AND deleted_at IS NULL)"
            " ON CONFLICT DO NOTHING",
            [(page_id, pages[n - 1]["id"], rank, page_id)
             for rank, n in enumerate(picks)],
        )  # fmt: skip
        resume(conn, now())  # a success ends any pause
    return None


# Pages whose related pages are older than their last change (or never picked)
STALE = """
SELECT p.id FROM page p WHERE p.deleted_at IS NULL AND (:all OR NOT EXISTS (
    SELECT 1 FROM enrich_run r WHERE r.page_id = p.id AND r.status = 'ok'
      AND json_extract(r.request, '$.purpose') = 'related'
      AND r.started_at >= p.updated_at))
ORDER BY p.created_at LIMIT :limit
"""


def related_pass(
    store: Store,
    call: Call | None = None,
    every: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """The nightly related pass (scrap enrich --related): a related call for each page
    changed since its related pages were last picked (or every page), oldest first.
    New pages pick older ones, and Related shows both ways, so older pages learn of
    new ones without a call of their own. It stops at a queue pause (or makes one:
    outage, credit, auth, the day's budget), as the worker does; other failures are
    counted and the next page tried. Returns the counts."""
    call = call or claude.complete
    budget = int(float(os.environ.get("SCRAP_BUDGET_DAY_USD", "3")) * 1e6)
    with store.connect() as conn:
        most = -1 if limit is None else limit
        ids = [r[0] for r in conn.execute(STALE, {"all": every, "limit": most})]
    counts: dict[str, Any] = {
        "pages": len(ids),
        "done": 0,
        "failed": 0,
        "stopped": None,
    }
    if dry_run:
        return counts
    for page_id in ids:
        stamp = now()
        with store.connect() as conn, transaction(conn):
            q = conn.execute("SELECT paused_until, reason FROM queue_state").fetchone()
            paused = q["paused_until"] is not None and q["paused_until"] > stamp
            over = not paused and spent_today(conn, stamp) >= budget
            announce = over and pause(conn, None, "budget", stamp)
        if announce:
            notify("budget")
        if paused or over:
            counts["stopped"] = q["reason"] if paused else "budget"
            break
        error = relate(store, call, page_id)
        if error is None:
            counts["done"] += 1
        elif error.cls in PAUSES:
            with store.connect() as conn, transaction(conn):
                announce = pause(conn, None, error.cls, now(), error.retry_after)
            if announce:
                notify(error.cls)
            counts["stopped"] = error.cls
            break
        else:
            counts["failed"] += 1
    return counts
