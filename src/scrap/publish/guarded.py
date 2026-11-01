"""The owner's guidance for Claude is never published (#538): a page's guidance for
its write-up (writeup_guidance) and for each image's reading (image_guidance) is a
private note. The publish mode never writes it; this refuses a page whose text holds
one anyway, as a check behind that.

A guidance note is found when its words (case and spacing aside) are in the page's
published text, unless they are also in what the page may show: its own text, title
and tags, and what Claude read and wrote of it (a reading, a write-up), which the
owner's words may echo. A short note (under MIN characters) is not looked for: a
word or two would refuse ordinary pages.
"""

import sqlite3

from ..store import Store
from .errors import CheckError
from .search import index_text

__all__ = ["MIN", "refuse_guidance"]

MIN = 12  # characters of a guidance note, once its spacing is collapsed

# The page's own words, which a note found in them may well be: its text, title and
# tags; the current readings of its captures' images and files; its write-up
OWN = """
SELECT body AS t FROM page WHERE id = :page
UNION ALL SELECT title FROM page WHERE id = :page
UNION ALL SELECT tag FROM tag WHERE page_id = :page
UNION ALL SELECT d.text FROM derived d JOIN capture c ON c.id = d.capture_id
    WHERE c.page_id = :page AND d.superseded_at IS NULL AND d.text IS NOT NULL
UNION ALL SELECT summary FROM writeup WHERE page_id = :page
UNION ALL SELECT text FROM writeup WHERE page_id = :page
"""
NOTES = """
SELECT text FROM writeup_guidance WHERE page_id = :page
UNION ALL SELECT g.text FROM image_guidance g JOIN capture c ON c.id = g.capture_id
    WHERE c.page_id = :page
"""


def _flat(text: str) -> str:
    return " ".join(text.split()).casefold()


def _texts(conn: sqlite3.Connection, sql: str, page_id: str) -> list[str]:
    return [r[0] or "" for r in conn.execute(sql, {"page": page_id})]


def refuse_guidance(store: Store, page_id: str, html: str) -> None:
    """CheckError if the page's published text holds any of its guidance for Claude
    (see the module)."""
    with store.connect() as conn:
        notes = [n for n in map(_flat, _texts(conn, NOTES, page_id)) if len(n) >= MIN]
        if not notes:
            return
        own = "\n".join(map(_flat, _texts(conn, OWN, page_id)))
    shown = _flat(index_text(html))
    if any(n in shown and n not in own for n in notes):
        raise CheckError(
            "Not published: the page holds the owner's guidance for Claude, which"
            " is never published.",
            "guidance",
        )
