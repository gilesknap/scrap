"""The owner's guidance for Claude's next reading of one image (#538): a note per
(capture, image), kept apart from what Claude read, as a page's write-up guidance is
(writeups.guidance). Photo ingest sends it with the image on the next Regenerate; it
never steers a write-up, and a write-up's never steers a reading. Never published.
These run on an open connection; the callers own the transaction.
"""

import sqlite3

from .constants import BY_CLAUDE, IS_IMAGE
from .errors import InvalidError, NotFoundError

MAX_GUIDANCE = 2_000  # characters, as a write-up's (enrich.MAX_GUIDANCE)


def get(conn: sqlite3.Connection, capture_id: str, sha: str) -> str | None:
    """The owner's guidance for an image's next reading, if any."""
    row = conn.execute(
        "SELECT text FROM image_guidance WHERE capture_id = ? AND source_sha256 = ?",
        (capture_id, sha),
    ).fetchone()
    return row[0] if row else None


def of_page(conn: sqlite3.Connection, page_id: str) -> dict[tuple[str, str], str]:
    """The guidance for each image of a page's captures, by (capture id, sha256)."""
    rows = conn.execute(
        "SELECT g.capture_id, g.source_sha256, g.text FROM image_guidance g"
        " JOIN capture c ON c.id = g.capture_id WHERE c.page_id = ?",
        (page_id,),
    )
    return {(r[0], r[1]): r[2] for r in rows}


def put(
    conn: sqlite3.Connection,
    capture_id: str,
    sha: str,
    text: str | None,
    author: str,
    stamp: str,
) -> str | None:
    """Keep the owner's guidance for an image's next reading (empty or None: none);
    what is kept. NotFoundError if the capture is not there (or its page is in the
    trash) or does not hold the file; InvalidError if the file is not an image Claude
    reads (a PDF or text file, which scrap reads itself, or an image of a capture
    Claude made, which it never reads: #521) or the text is too long."""
    if text is not None and len(text) > MAX_GUIDANCE:
        raise InvalidError(f"guidance is at most {MAX_GUIDANCE} characters")
    row = conn.execute(
        f"SELECT {IS_IMAGE.format(b='b')} AS image, {BY_CLAUDE.format(c='c')} AS claude"
        " FROM capture c JOIN page p ON p.id = c.page_id"
        " JOIN capture_blob cb ON cb.capture_id = c.id"
        " JOIN blob b ON b.sha256 = cb.sha256"
        " WHERE c.id = ? AND cb.sha256 = ? AND p.deleted_at IS NULL",
        (capture_id, sha),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"{capture_id}/{sha}")
    if not row["image"]:
        raise InvalidError("only an image Claude reads has guidance")
    if row["claude"]:
        raise InvalidError("Claude doesn't read an image it placed itself")
    kept = (text or "").strip()
    if not kept:
        conn.execute(
            "DELETE FROM image_guidance WHERE capture_id = ? AND source_sha256 = ?",
            (capture_id, sha),
        )
        return None
    conn.execute(
        "INSERT INTO image_guidance VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (capture_id, source_sha256) DO UPDATE SET text = excluded.text,"
        " author = excluded.author, updated_at = excluded.updated_at",
        (capture_id, sha, kept, author, stamp),
    )
    return kept
