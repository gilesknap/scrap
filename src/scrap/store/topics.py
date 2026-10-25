"""Claude's topic pages (#261), as stored: which pages are topics, their sources, and
the index of them all.

A topic is a real page (kind reference) marked by a row in topic; its body is the
owner's notes, and Claude's synthesis is its write-up (store.writeups). Its sources
(topic_source) are the synthesis's inputs; one the owner excluded stays, excluded, so
discovery never adds it again. A topic in the trash keeps its key, so discovery never
makes it again: the trash is the veto. These run on an open connection; the callers
own the transaction. Before migration 13 there are no topics.
"""

import json
import re
import sqlite3
import unicodedata
from typing import Any

from .helpers import new_ulid

# A topic page p (SQL)
IS_TOPIC = "EXISTS (SELECT 1 FROM topic t WHERE t.page_id = {p}.id)"
NOT_KEY = re.compile(r"[^\w]+|_+")  # what a key keeps: letters and digits, else -
MAX_KEY = 80


def _rows(conn: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, args)]  # below db: as db._rows


def topic_key(name: str) -> str:
    """A topic's key: its name in lower case (NFKC), each run of anything but letters
    and digits one -, at most MAX_KEY characters; "RTEMS IOCs" is rtems-iocs."""
    text = unicodedata.normalize("NFKC", name).casefold()
    return NOT_KEY.sub("-", text).strip("-")[:MAX_KEY].strip("-")


def is_topic(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether a page is a topic (False before migration 13)."""
    try:
        sql = "SELECT 1 FROM topic WHERE page_id = ?"
        return conn.execute(sql, (page_id,)).fetchone() is not None
    except sqlite3.OperationalError:  # no such table: an older schema
        return False


def key_of(conn: sqlite3.Connection, page_id: str) -> str | None:
    """A topic page's key, else None."""
    try:
        sql = "SELECT key FROM topic WHERE page_id = ?"
        row = conn.execute(sql, (page_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def create(
    conn: sqlite3.Connection, title: str, key: str, slug: str, author: str, stamp: str
) -> str | None:
    """A new topic page (kind reference, chosen; an empty body: the owner's notes) and
    its topic row; its id. None if a topic has that key already (in the trash too)."""
    if conn.execute("SELECT 1 FROM topic WHERE key = ?", (key,)).fetchone():
        return None
    page_id = new_ulid()
    conn.execute(
        "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields, created_at,"
        " updated_at) VALUES (?, ?, ?, '', 'reference', 1, '{}', ?, ?)",
        (page_id, slug, title, stamp, stamp),
    )
    conn.execute(
        "INSERT INTO page_rev VALUES (?, 1, ?, '', ?, ?)",
        (page_id, title, author, stamp),
    )
    conn.execute("INSERT INTO topic VALUES (?, ?, ?)", (page_id, key, stamp))
    return page_id


def add_sources(
    conn: sqlite3.Connection,
    topic_id: str,
    page_ids: list[str],
    added_by: str,
    stamp: str,
) -> int:
    """Add pages (not in the trash, not topics) to a topic's sources; one there
    already, or excluded by the owner, is left as it is. How many were added."""
    cur = conn.executemany(
        "INSERT INTO topic_source (topic_id, page_id, added_by, added_at, changed_at)"
        " SELECT ?, p.id, ?, ?, ? FROM page p WHERE p.id = ?"
        f" AND p.deleted_at IS NULL AND NOT {IS_TOPIC.format(p='p')}"
        " ON CONFLICT DO NOTHING",
        [(topic_id, added_by, stamp, stamp, p) for p in page_ids],
    )
    return cur.rowcount


def exclude(conn: sqlite3.Connection, topic_id: str, page_id: str, stamp: str) -> bool:
    """The owner takes a source out of a topic: kept, excluded, so discovery never adds
    it again. Whether it was a source still in."""
    cur = conn.execute(
        "UPDATE topic_source SET excluded = 1, changed_at = ?"
        " WHERE topic_id = ? AND page_id = ? AND excluded = 0",
        (stamp, topic_id, page_id),
    )
    return cur.rowcount > 0


def sources(
    conn: sqlite3.Connection, topic_id: str, excluded: bool = False
) -> list[dict[str, Any]]:
    """A topic's sources not in the trash, first added first: id, slug, title, kind,
    added_by, added_at and excluded; with excluded, those the owner took out too."""
    try:
        return _rows(
            conn,
            "SELECT p.id, p.slug, p.title, p.kind, s.added_by, s.added_at,"
            " s.excluded FROM topic_source s JOIN page p ON p.id = s.page_id"
            " WHERE s.topic_id = ? AND p.deleted_at IS NULL AND (? OR s.excluded = 0)"
            " ORDER BY s.added_at, p.created_at, p.id",
            topic_id, excluded,
        )  # fmt: skip
    except sqlite3.OperationalError:
        return []


def of_page(conn: sqlite3.Connection, page_id: str) -> list[dict[str, Any]]:
    """The topics (not in the trash) a page is a source of, by title: id, slug,
    title."""
    try:
        return _rows(
            conn,
            "SELECT p.id, p.slug, p.title FROM topic_source s"
            " JOIN page p ON p.id = s.topic_id WHERE s.page_id = ?"
            " AND s.excluded = 0 AND p.deleted_at IS NULL"
            " ORDER BY p.title COLLATE NOCASE, p.id",
            page_id,
        )  # fmt: skip
    except sqlite3.OperationalError:
        return []


def every(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every topic, the trash's too (their keys are vetoes): id, key, title, trashed,
    and its sources in (their ids, excluded or trashed ones left out)."""
    rows = _rows(
        conn,
        "SELECT p.id, t.key, p.title, p.deleted_at IS NOT NULL AS trashed,"
        " (SELECT json_group_array(s.page_id) FROM topic_source s"
        "  JOIN page q ON q.id = s.page_id WHERE s.topic_id = p.id"
        "  AND s.excluded = 0 AND q.deleted_at IS NULL) AS sources"
        " FROM topic t JOIN page p ON p.id = t.page_id ORDER BY t.created_at, p.id",
    )
    return [{**r, "sources": json.loads(r["sources"])} for r in rows]


def area(tagged: list[tuple[str, str]]) -> str | None:
    """The top-level tag most common among some pages' tags, (page, tag) pairs: each
    page counts a top-level tag once (a/b and a/c are one a), ties by name; None if
    they have none."""
    counts: dict[str, int] = {}
    for top in {(page, tag.split("/", 1)[0]) for page, tag in tagged}:
        counts[top[1]] = counts.get(top[1], 0) + 1
    return min(counts, key=lambda t: (-counts[t], t)) if counts else None


def index(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The topics (not in the trash), made from data with no model call: id, slug,
    title, summary (its synthesis's lead, '' before one), sources (how many are in),
    updated_at (its synthesis's, else the page's), and area (the top-level tag most
    common among its sources' tags, None if they have none). Grouped by area, the
    biggest first, those with none last; by title within one."""
    try:
        rows = _rows(
            conn,
            "SELECT p.id, p.slug, p.title, coalesce(w.summary, '') AS summary,"
            " coalesce(w.created_at, p.updated_at) AS updated_at,"
            " (SELECT count(*) FROM topic_source s JOIN page q ON q.id = s.page_id"
            "  WHERE s.topic_id = p.id AND s.excluded = 0 AND q.deleted_at IS NULL)"
            " AS sources,"
            " (SELECT json_group_array(json_array(s.page_id, g.tag))"
            "  FROM topic_source s JOIN page q ON q.id = s.page_id"
            "  JOIN tag g ON g.page_id = s.page_id"
            "  WHERE s.topic_id = p.id AND s.excluded = 0 AND q.deleted_at IS NULL)"
            " AS tags"
            " FROM topic t JOIN page p ON p.id = t.page_id"
            " LEFT JOIN writeup w ON w.page_id = p.id AND w.superseded_at IS NULL"
            " WHERE p.deleted_at IS NULL",
        )
    except sqlite3.OperationalError:  # no such table: an older schema
        return []
    for r in rows:
        r["area"] = area([(p, t) for p, t in json.loads(r.pop("tags"))])
    size: dict[str | None, int] = {}
    for r in rows:
        size[r["area"]] = size.get(r["area"], 0) + 1
    rows.sort(key=lambda r: (r["area"] is None, -size[r["area"]], r["area"] or "",
                             r["title"].casefold(), r["id"]))  # fmt: skip
    return rows
