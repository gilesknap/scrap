"""Enrich: related pages, one call for a page and the nightly pass."""

import json
import os
from collections.abc import Callable
from typing import Any

from .. import claude
from ..ingest import PAUSES, notify, pause, resume, spent_today
from ..store import Store, model_summary, now, transaction, writeups
from .checking import checked_related, record
from .constants import RELATED_SCHEMA, STALE
from .finding import CANDIDATES
from .prompts import page_images, related_message, related_prompt
from .types import Call


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
        images = page_images(conn, page_id)
        up = writeups.shown(conn, page_id)
    system, version = related_prompt(pages)
    messages = related_message(page, tags, summary, images, up["text"] if up else "")
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


def related_pass(
    store: Store,
    call: Call | None = None,
    every: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """The nightly related pass (scrap enrich --related): a related call for each page
    changed, or with a photo read, since its related pages were last picked (or every
    page), oldest first. New pages pick older ones, and Related shows both ways, so
    older pages learn of new ones without a call of their own. It stops at a queue
    pause (or makes one: outage, credit, auth, the day's budget), as the worker does;
    other failures are counted and the next page tried. Returns the counts."""
    call = call or claude.complete
    budget = int(float(os.environ.get("SCRAP_BUDGET_DAY_USD", "3")) * 1e6)
    with store.connect() as conn:
        most = -1 if limit is None else limit
        ids = [r[0] for r in conn.execute(STALE, {"all": every, "limit": most})]
    return run_pass(store, ids, lambda p: relate(store, call, p), budget, dry_run)


def run_pass(
    store: Store,
    ids: list[str],
    one: Callable[[str], claude.CallError | None],
    budget: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """One call (one) for each page, here and now, as a pass from the command line
    does it: before each, it stops at a queue pause or at the day's budget (pausing
    the queue for it); a call that pauses the queue (outage, credit, auth) stops it
    too; other failures are counted and the next page tried. Returns the counts."""
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
        error = one(page_id)
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
