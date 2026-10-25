"""Search indexing and the enrich queue."""

import json
import os
import sqlite3
from datetime import UTC, datetime

from ..markdown import plain
from ..query import (
    CONTROL,
)
from .constants import (
    ENRICH_ENQUEUE,
    ENRICH_KINDS,
    FIRST_READ,
    NOT_BY_INGEST,
    RELATED_ENQUEUE,
)
from .helpers import now, unlink
from .writeups import current as current_writeup
from .writeups import due as writeup_due
from .writeups import has_board
from .writeups import shown as shown_writeup


def index_page(conn: sqlite3.Connection, page_id: str) -> None:
    """(Re)make a page's own search chunks: one from its title, tags, summary and
    body, and one from its current write-up's text, if any (its derived text has
    chunks of its own). No control characters: snippets mark hits with \x02 and \x03.
    Each becomes a space, so a lone \r or \v still separates two words."""
    title, body, fields = conn.execute(
        "SELECT title, body, fields FROM page WHERE id = ?", (page_id,)
    ).fetchone()
    tags = " ".join(
        r[0] for r in conn.execute("SELECT tag FROM tag WHERE page_id = ?", (page_id,))
    )
    summary = json.loads(fields).get("summary")
    summary = summary if isinstance(summary, str) else model_summary(conn, page_id)
    # The text as words (markdown.py); the others are short, and not Markdown
    parts = (unlink(title), tags, unlink(summary), plain(body))
    clean = [CONTROL.sub(" ", x) for x in parts]
    conn.execute(
        "DELETE FROM chunk WHERE page_id = ? AND derived_id IS NULL", (page_id,)
    )
    conn.execute(
        "INSERT INTO chunk (page_id, ord, title, tags, summary, text)"
        " VALUES (?, 0, ?, ?, ?, ?)",
        (page_id, *clean),
    )
    up = shown_writeup(conn, page_id)
    if up is not None and up["text"]:
        conn.execute(
            "INSERT INTO chunk (page_id, ord, text) VALUES (?, 1, ?)",
            (page_id, CONTROL.sub(" ", plain(up["text"]))),
        )


def model_summary(conn: sqlite3.Connection, page_id: str) -> str:
    """The summary Claude wrote for a page: its current write-up's (a board's), else
    enrich's, else ''. Before migration 9 there is no enrichment table: ''."""
    up = shown_writeup(conn, page_id)
    if up is not None and up["summary"]:
        return up["summary"]
    try:
        row = conn.execute(
            "SELECT summary FROM enrichment WHERE page_id = ?", (page_id,)
        ).fetchone()
    except sqlite3.OperationalError:
        return ""
    return row[0] if row else ""


def enrich_on() -> bool:
    """Whether Claude enriches text pages: with ingest on (SCRAP_INGEST), unless
    SCRAP_ENRICH is off."""
    on = ("on", "1", "true", "yes")
    ingest = os.environ.get("SCRAP_INGEST", "off").lower() in on
    return ingest and os.environ.get("SCRAP_ENRICH", "on").lower() in on


def should_enrich(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether enrich reads this page on a capture, save or backfill: its kind is in
    ENRICH_KINDS and it was not made with a photo or file capture (NOT_BY_INGEST)."""
    row = conn.execute(
        "SELECT p.kind FROM page p WHERE p.id = ? AND " + NOT_BY_INGEST.format(p="p"),
        (page_id,),
    ).fetchone()
    return row is not None and row[0] in ENRICH_KINDS


def debounce() -> float:
    """Seconds an enrich job waits after a save, so a burst of edits makes one call."""
    try:
        return max(0.0, float(os.environ.get("SCRAP_ENRICH_DEBOUNCE", "60")))
    except ValueError:
        return 60.0


def stamp_after(seconds: float) -> str:
    t = datetime.now(UTC).timestamp() + seconds
    return (
        datetime.fromtimestamp(t, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def queue_enrich(
    conn: sqlite3.Connection, page_id: str, reason: str, delay: float = 0.0
) -> None:
    """Queue (or move) a page's enrich job, to run in delay seconds."""
    conn.execute(
        ENRICH_ENQUEUE,
        {"page": page_id, "reason": reason, "run_after": stamp_after(delay),
         "now": now()},
    )  # fmt: skip


def queue_related(conn: sqlite3.Connection, page_id: str) -> None:
    """Queue a page's first related call, now, with enrich on (RELATED_ENQUEUE): on
    its first enrich, or when photo ingest has read its first photo capture."""
    if enrich_on():
        conn.execute(RELATED_ENQUEUE, {"page": page_id, "now": now()})


def queue_related_on_read(conn: sqlite3.Connection, capture_id: str) -> None:
    """After photo ingest read one of a capture's photos: the page's first related
    call, if that was the last of its first photo capture still to read."""
    row = conn.execute(FIRST_READ, {"capture": capture_id}).fetchone()
    if row is not None:
        queue_related(conn, row[0])


def queue_writeup(conn: sqlite3.Connection, page_id: str) -> None:
    """Queue (or take over) a page's enrich job as a write-up, now, with enrich on."""
    if enrich_on():
        queue_enrich(conn, page_id, "writeup")


def queue_topic(conn: sqlite3.Connection, page_id: str) -> None:
    """Queue (or take over) a topic page's enrich job as its synthesis (#261), now,
    with enrich on."""
    if enrich_on():
        queue_enrich(conn, page_id, "topic")


def queue_after_read(conn: sqlite3.Connection, capture_id: str) -> None:
    """After photo ingest read (or gave up on) one of a capture's photos. A board page
    (a whiteboard or diagram, not a list of actions) gets its write-up once all its
    photos are read and a board image was read since its last one; its first related
    call follows the write-up (Enricher), so it sees it. Any other page: its first
    related call, once its first photo capture is read (queue_related_on_read)."""
    row = conn.execute(
        "SELECT page_id FROM capture WHERE id = ?", (capture_id,)
    ).fetchone()
    if row is not None and enrich_on() and has_board(conn, row[0]):
        if writeup_due(conn, row[0]):
            queue_writeup(conn, row[0])
        return
    if row is not None and current_writeup(conn, row[0]) is not None:
        index_page(conn, row[0])  # no longer a board: its write-up leaves the index
    queue_related_on_read(conn, capture_id)


def index_all(conn: sqlite3.Connection) -> None:
    """Every page's own chunk again (the trash's too: undo brings a page back)."""
    for (page_id,) in conn.execute("SELECT id FROM page").fetchall():
        index_page(conn, page_id)
