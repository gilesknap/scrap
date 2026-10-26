"""What a page is (#280): every test of a page's role, in one place, as SQL fragments
(templates on a page alias {p}) and Python helpers on an open connection.

A page's first capture decides what the page is; later captures only add content
(#260): what automation infers from them never changes its kind, title or tags, or
whether enrich or ingest maintains it. The owner can always change kind, title and tags
by hand. Each question has one answer here, and the table in
docs/explanations/llm-calls.md (Page roles) matches it row for row:

- origin: human, claude (written over MCP), topic (Claude's topic page) or gc (a review
  page scrap gc made), worked out from the page's captures and the topic table;
- maintainer: enrich (on capture and save) or ingest (photo ingest; enrich on Ask only);
- write-up: board, topic or none;
- what automation may change: the title (until the first edit), the kind (while
  nobody filed it) and the tags, from the first capture only;
- whether photos may be added (not to a topic page).

The callers own the transaction. Only constants is below this module, so every other
store module, and the rest of scrap, can use it.
"""

import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from .constants import CLAUDE, ENRICH_KINDS, MCP, PINNED_SLUG

Origin = Literal["human", "claude", "topic", "gc"]
Maintainer = Literal["enrich", "ingest"]
WriteupType = Literal["board", "topic"]

GC = "gc"  # the source of the capture scrap gc makes a review page with (orphans.py)

# ---- the first capture

# The id of a page's first capture (SQL; page: an expression for the page's id).
# Captures received at the same moment (an import's): a file capture last, then one
# with no files before one with them, then the id, so an import's main capture (its
# text, with its images) is first whatever its hash-derived id.
FIRST_CAPTURE = (
    "(SELECT f.id FROM capture f WHERE f.page_id = {page}"
    " ORDER BY f.received_at, f.kind = 'file',"
    " EXISTS (SELECT 1 FROM capture_blob b WHERE b.capture_id = f.id), f.id LIMIT 1)"
)
# Whether a capture {c} is its page's first (SQL)
IS_FIRST = "{c}.id = " + FIRST_CAPTURE.format(page="{c}.page_id")


def first_capture(conn: sqlite3.Connection, cid: str) -> tuple[str, bool]:
    """A capture's page id, and whether the capture is that page's first: the one
    whose photo may set the page's title, kind and tags."""
    row = conn.execute(
        f"SELECT c.page_id, {IS_FIRST.format(c='c')} FROM capture c WHERE c.id = ?",
        (cid,),
    ).fetchone()
    return row[0], bool(row[1])


# ---- origin

# A topic page p: a row in topic (#261). Before migration 13 there is no topic table.
IS_TOPIC = "EXISTS (SELECT 1 FROM topic t WHERE t.page_id = {p}.id)"
# A review page: one scrap gc made, gathering capture files no page shows (its
# capture's source is gc), whatever it is titled now (orphans.py). Any capture: gc only
# ever makes such a page, it never adds a capture to one.
REVIEW = (
    "EXISTS (SELECT 1 FROM capture c WHERE c.page_id = {p}.id AND c.source = '"
    + GC
    + "')"
)
# Written by Claude over MCP: the page's first capture came over MCP
BY_CLAUDE = (
    "coalesce((SELECT c.source FROM capture c WHERE c.id = "
    + FIRST_CAPTURE.format(page="{p}.id")
    + "), '') = '"
    + MCP
    + "'"
)
# Any capture of the page came over MCP: search's is:claude test (MCP read's
# written_by_claude is has_mcp_capture). TODO(#280, for the owner): this is not
# BY_CLAUDE's first-capture test, though the two find the same pages today: an mcp
# capture only ever makes a page (MCP write) or is appended to one whose first capture
# is mcp (Store.import_page refuses any other). Step 3's origin column replaces both.
HAS_MCP_CAPTURE = (
    "EXISTS (SELECT 1 FROM capture c WHERE c.page_id = {p}.id AND c.source = '"
    + MCP
    + "')"
)
# A page's origin (SQL): a topic, else gc's, else Claude's, else the owner's
ORIGIN = (
    f"CASE WHEN {IS_TOPIC} THEN 'topic' WHEN {REVIEW} THEN 'gc'"
    f" WHEN {BY_CLAUDE} THEN 'claude' ELSE 'human' END"
)
# Claude changed its text over MCP after it was made (is:claude-edited): a text
# revision by Claude after the first (an edit_page, a revert, an append). Only MCP
# writes as CLAUDE, so this is never the photo worker's or the PWA's.
CLAUDE_EDITED = (
    "EXISTS (SELECT 1 FROM page_rev r WHERE r.page_id = {p}.id AND r.rev > 1"
    " AND r.author = '" + CLAUDE + "')"
)


def _one(conn: sqlite3.Connection, fragment: str, page_id: str) -> bool:
    row = conn.execute(
        f"SELECT {fragment.format(p='p')} FROM page p WHERE p.id = ?", (page_id,)
    ).fetchone()
    return bool(row and row[0])


def is_topic(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether a page is a topic (False before migration 13)."""
    try:
        sql = "SELECT 1 FROM topic WHERE page_id = ?"
        return conn.execute(sql, (page_id,)).fetchone() is not None
    except sqlite3.OperationalError:  # no such table: an older schema
        return False


def is_review(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether a page is one of gc's review pages (REVIEW)."""
    return _one(conn, REVIEW, page_id)


def by_claude(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether a page was written over MCP (its first capture's source)."""
    row = conn.execute(
        "SELECT source FROM capture WHERE id = " + FIRST_CAPTURE.format(page="?"),
        (page_id,),
    ).fetchone()
    return bool(row) and row[0] == MCP


def has_mcp_capture(captures: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any of a page's captures (as Store.page lists them) came over MCP:
    HAS_MCP_CAPTURE, in Python (see its TODO)."""
    return any(c["source"] == MCP for c in captures)


def edited_by_claude(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether Claude changed a page's text over MCP after it was made
    (CLAUDE_EDITED)."""
    return _one(conn, CLAUDE_EDITED, page_id)


def origin(conn: sqlite3.Connection, page_id: str) -> Origin:
    """A page's origin, as ORIGIN has it: topic, gc, claude or human (in that
    order). Before migration 13, never topic."""
    if is_topic(conn, page_id):
        return "topic"
    if is_review(conn, page_id):
        return "gc"
    return "claude" if by_claude(conn, page_id) else "human"


# ---- maintainer: enrich or photo ingest

# A page made by a photo or file capture (its first) is read by ingest, not enrich,
# whatever its kind (a photo page is stored as a note until ingest reclassifies it).
# A page with no capture (a topic) is not. gc's review page is a file capture with no
# files: ingest's, so enrich leaves it alone.
NOT_BY_INGEST = (
    "coalesce((SELECT c.kind FROM capture c WHERE c.id = "
    + FIRST_CAPTURE.format(page="{p}.id")
    + "), '') NOT IN ('photo', 'file')"
)


def maintainer(conn: sqlite3.Connection, page_id: str) -> Maintainer:
    """Who reads a page as it changes: ingest if its first capture is a photo or
    file (NOT_BY_INGEST), else enrich (should_enrich adds its kind)."""
    return "enrich" if _one(conn, NOT_BY_INGEST, page_id) else "ingest"


def should_enrich(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether enrich reads this page on a capture, save or backfill: its kind is in
    ENRICH_KINDS, it was not made with a photo or file capture (NOT_BY_INGEST) and it
    is not the Pinned page (a list of links: nothing for Claude to read).
    TODO(#280, for the owner): a topic page has no capture, so it passes
    NOT_BY_INGEST; only its kind (document) keeps it out. One the owner re-kinds as a
    note queues enrich on each save, which the enricher's topic branch then finishes
    with no call."""
    row = conn.execute(
        "SELECT p.kind FROM page p WHERE p.id = ? AND p.slug != ? AND "
        + NOT_BY_INGEST.format(p="p"),
        (page_id, PINNED_SLUG),
    ).fetchone()
    return row is not None and row[0] in ENRICH_KINDS


# ---- write-up: board, topic or none

# Whether a page has a board image (writeups.BOARD_IMAGES' test, as SQL on a page p):
# a current photo reading says whiteboard or diagram, and did not judge it a list of
# actions (a to-do sticky becomes a checklist instead). The reading's kind, not the
# page's: an added photo can make any page a board.
HAS_BOARD = """EXISTS (
    SELECT 1 FROM capture c JOIN derived d ON d.capture_id = c.id
    LEFT JOIN model_run r ON r.id = d.run_id
    WHERE c.page_id = {p}.id AND d.kind = 'description' AND d.superseded_at IS NULL
      AND json_extract(d.data, '$.kind') IN ('whiteboard', 'diagram')
      AND coalesce(json_extract(r.output, '$.intent'), '') <> 'list-of-actions')"""
# Whether a page's write-up is on show (SQL on a page p): a board page's or a topic's
SHOWN = f"({HAS_BOARD} OR {IS_TOPIC})"


def has_board(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether a page has a board image (HAS_BOARD)."""
    return _one(conn, HAS_BOARD, page_id)


def writeup_type(conn: sqlite3.Connection, page_id: str) -> WriteupType | None:
    """A page's write-up: board (a board image: write_up explains it), topic (its
    synthesis) or None (SHOWN, with board first, as writeups.view has it).
    TODO(#280, for the owner): a page both would be a board here and in view, but a
    topic in OUTDATED (HAS_BOARD AND NOT IS_TOPIC) and Store.page's related via. None
    can be both today: add_photos refuses a topic, and a topic has no capture."""
    if has_board(conn, page_id):
        return "board"
    return "topic" if is_topic(conn, page_id) else None


# ---- what automation may change

# A page's title is still as made: rev 1's, and no later text revision (SQL; page: an
# expression for the page's id). The test of both TITLE_CASes (ingest's from a photo,
# enrich's from a fetched link).
TITLE_UNTOUCHED = (
    "title = (SELECT title FROM page_rev WHERE page_id = {page} AND rev = 1)"
    " AND NOT EXISTS (SELECT 1 FROM page_rev WHERE page_id = {page} AND rev > 1)"
)
# A page p nobody filed: a note, its kind not chosen (kind_fixed 0). Automation may
# file it (photo ingest: a whiteboard or document; a fetched link: a read; its task
# boxes: a todo).
UNFILED = "{p}.kind = 'note' AND {p}.kind_fixed = 0"


def may_retitle(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether automation may still set a page's title (TITLE_UNTOUCHED): nobody has
    edited its text or title since it was made. The photo worker also needs the first
    capture's first photo, with no text; enrich, a link title as captured."""
    sql = f"SELECT 1 FROM page WHERE id = :page AND {TITLE_UNTOUCHED}"
    return (
        conn.execute(sql.format(page=":page"), {"page": page_id}).fetchone() is not None
    )


def may_rekind(kind: str, fixed: Any, kinds: tuple[str, ...] = ("note",)) -> bool:
    """Whether automation may change a page's kind: nobody chose it (kind_fixed 0)
    and it is still one of kinds (by default a note: UNFILED). The photo worker's
    task boxes also take ingest's whiteboard; Claude's boxes coming off take a todo."""
    return not fixed and kind in kinds


def takes_photos(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether photos may be added to a page: not to a topic, whose synthesis is its
    write-up (a board photo would queue a board's over it)."""
    return not is_topic(conn, page_id)
