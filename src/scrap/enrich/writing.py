"""Enrich: Claude's write-up of a board page (#256), one call, and the backfill. Any
other page with an image can have one on request (#453), made with the readout prompt.

A board page is one with a whiteboard or diagram image that is not a list of actions
(store.roles.HAS_BOARD). Its write-up explains the board in Markdown sections,
from the photos themselves (the JPEGs photo ingest sent, at most MAX_BOARDS), what was
read from them, the page's title, tags and text, and the owner's guidance. It may link
to the page's related candidates (CANDIDATES), cited by number and made page links
here, so it cannot name a page that does not exist. It is stored apart from the text
as a new version (store.writeups), never in the body.
"""

import io
import json
from typing import Any

from .. import claude, preview
from ..ingest.constants import budget_day_micros
from ..store import NotFoundError, Store, now, roles, transaction, writeups
from .checking import checked_writeup, record
from .constants import BOARDS, MAX_BOARDS, WRITEUP_SCHEMA
from .finding import CANDIDATES
from .prompts import writeup_message, writeup_prompt
from .relating import run_pass
from .types import Call


def _sent(store: Store, board: dict[str, Any]) -> str | None:
    """The JPEG to send of a board image: the one photo ingest sent, if it is still
    stored, else made again (preview.for_claude) and stored; None if neither."""
    if board["sent"]:
        try:
            store.blob(board["sent"])
            return board["sent"]
        except NotFoundError:
            pass
    try:
        jpeg, _, _ = preview.for_claude(store, board["sha256"])
    except Exception:  # noqa: BLE001  undecodable, or gone: its text is still sent
        return None
    sha, size = store.put_blob(io.BytesIO(jpeg))
    with store.connect() as conn, transaction(conn):
        conn.execute(
            "INSERT INTO blob VALUES (?, 'image/jpeg', ?, ?) ON CONFLICT DO NOTHING",
            (sha, size, now()),
        )
    return sha


def write_up(
    store: Store,
    call: Call,
    page_id: str,
    job_id: int | None = None,
    boards_only: bool = False,
) -> claude.CallError | None:
    """One write-up call for a board page; on success its write-up is a new current
    version, and the page is indexed again. The run is recorded either way; a failure
    is returned for the caller to act on (pause, charge or carry on). None: done, or
    nothing to do (the page is in the trash, or has no board image). Ask (boards_only)
    writes up a board only: any other page's is asked for, never made on its own
    (#453)."""
    with store.connect() as conn:
        page = conn.execute(
            "SELECT * FROM page WHERE id = ? AND deleted_at IS NULL", (page_id,)
        ).fetchone()
        if page is None:
            return None
        if boards_only and not roles.has_board(conn, page_id):
            return None
        boards = writeups.board_images(conn, page_id)
        if not boards:
            return None
        tags = [r[0] for r in conn.execute(
            "SELECT tag FROM tag WHERE page_id = ?", (page_id,))]  # fmt: skip
        guidance = writeups.guidance(conn, page_id)
        pages = CANDIDATES(conn, page_id)
        slug_of = dict(conn.execute(
            "SELECT id, slug FROM page WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps([p["id"] for p in pages]),),
        ).fetchall())  # fmt: skip
    slugs = [slug_of.get(p["id"], "") for p in pages]
    sent = [_sent(store, b) for b in boards[:MAX_BOARDS]]
    with store.connect() as conn:
        readout = not roles.has_board(conn, page_id)  # asked for, not a board (#453)
    system, version = writeup_prompt(pages, readout)
    messages = writeup_message(page, tags, boards, sent, guidance, readout)
    model = claude.model_name()
    request = {
        "purpose": "writeup", "model": model, "max_tokens": claude.MAX_TOKENS,
        "effort": claude.EFFORT, "system": system, "messages": messages,
        "schema": WRITEUP_SCHEMA, "candidates": [p["id"] for p in pages],
        "guidance": guidance, "backend": claude.backend(),
    }  # fmt: skip
    with store.connect() as conn, transaction(conn):
        run_id = conn.execute(
            "INSERT INTO enrich_run (page_id, job_id, model, prompt_version, request,"
            " started_at) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (page_id, job_id, model, version, json.dumps(request), now()),
        ).fetchone()[0]

    def blob(sha: str) -> tuple[bytes, str]:
        path, mime = store.blob(sha)
        return path.read_bytes(), mime

    try:
        done = call(
            model, system, messages, WRITEUP_SCHEMA, blob,
            effort=claude.EFFORT, max_tokens=claude.MAX_TOKENS,
        )  # fmt: skip
        try:
            out = checked_writeup(done.output, slugs)
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
        record(conn, run_id, done, status="ok", output=json.dumps(out))
        alive = conn.execute(
            "SELECT 1 FROM page WHERE id = ? AND deleted_at IS NULL", (page_id,)
        ).fetchone()
        if alive:
            writeups.put(
                conn, page_id, now(), producer=done.served_model, run_id=run_id,
                prompt_version=version, summary=out["summary"], text=out["text"],
                guidance=guidance,
            )  # fmt: skip
            store.reindex(conn, page_id)
    return None


def writeup_pass(
    store: Store,
    call: Call | None = None,
    every: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    outdated: bool = False,
) -> dict[str, Any]:
    """Write-ups here and now (scrap enrich --writeups): one for each board page with
    none; with outdated, each with an outdated write-up instead (writeups.OUTDATED, as
    is:outdated; how a new prompt is rolled out); with
    every, every board page. Oldest first, at most limit. It stops at a queue
    pause (or makes one: outage, credit, auth, the day's budget), as the related pass
    does; other failures are counted and the next page tried. Returns the counts."""
    call = call or claude.complete
    budget = budget_day_micros()
    with store.connect() as conn:
        most = -1 if limit is None else limit
        ids = [r[0] for r in conn.execute(BOARDS, {
            "all": every, "outdated": outdated, "limit": most,
            "version": writeup_prompt([])[1],  # outdated: made with another
        })]  # fmt: skip
    return run_pass(store, ids, lambda p: write_up(store, call, p), budget, dry_run)
