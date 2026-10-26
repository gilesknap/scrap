"""Enrich: the candidates a related call may pick from."""

import json
import logging
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from ..markdown import plain
from ..store import model_summary, roles
from .constants import BY_TAGS, BY_WORDS, MAX_CANDIDATES, QUERY_WORDS, WORD
from .prompts import page_images

log = logging.getLogger(__name__)


def search_words(texts: Iterable[str], most: int = QUERY_WORDS) -> list[str]:
    """The first most distinct words (WORD, lower case) of texts, in order; it stops
    reading texts once it has them."""
    words: dict[str, None] = {}
    for text in texts:
        for match in WORD.finditer(text):
            words.setdefault(match.group().lower(), None)
            if len(words) >= most:
                return list(words)
    return list(words)


def page_texts(
    conn: sqlite3.Connection, page_id: str, title: str, about: str, body: str
) -> Iterator[str]:
    """A page's texts to search by, most telling first: its title, tags and summary,
    then what photo ingest read from its images (their text, then their
    descriptions), then its own text (made plain only if it is reached)."""
    yield title
    yield " ".join(r[0] for r in conn.execute(
        "SELECT tag FROM tag WHERE page_id = ?", (page_id,)))  # fmt: skip
    yield about
    images = page_images(conn, page_id)
    yield from (i["text"] or "" for i in images)
    yield from (i["description"] or "" for i in images)
    yield plain(body)


def candidates(
    conn: sqlite3.Connection, page_id: str, limit: int = MAX_CANDIDATES
) -> list[dict[str, Any]]:
    """The pages Claude may pick as related to a page, at most limit whatever the
    library's size: those sharing the most tags with it (BY_TAGS), then those whose
    title, tags, summary or text best match its words (full-text search, BY_WORDS),
    then the most recently changed; none in the trash. Its words: the first
    QUERY_WORDS distinct ones of its title, tags and summary, then of what was read
    from its images (their text, then their descriptions), then of its own text, so
    a photo page with no summary is searched by what is in the photo.
    Swappable (CANDIDATES): embeddings (#53) if these prove too weak."""
    me = conn.execute(
        "SELECT p.title, p.fields, p.body FROM page p WHERE p.id = ?", (page_id,)
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
        about = human if isinstance(human, str) else model_summary(conn, page_id)
        words = search_words(page_texts(conn, page_id, me[0], about, me[2]))
        query = " OR ".join(f'"{w}"' for w in words)
        sql = (
            "SELECT c.page_id FROM chunk_fts JOIN chunk c ON c.id = chunk_fts.rowid"
            f" JOIN page p ON p.id = c.page_id WHERE chunk_fts MATCH :q AND {alive}"
            " ORDER BY bm25(chunk_fts) LIMIT :n"
        )
        args = {"q": query, "id": page_id, "n": BY_WORDS * 3}
        try:
            found = conn.execute(sql, args).fetchall() if query else []
        except sqlite3.OperationalError as error:  # fail soft: tags and recency only
            log.warning("related candidates: no word search for %s: %s", page_id, error)
            found = []
        n = 0
        for (other,) in found:
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
            "SELECT p.id, p.title, p.fields,"
            " coalesce(nullif(w.summary, ''), e.summary, '') AS summary,"
            " (SELECT group_concat(tag, '\x1f') FROM tag WHERE page_id = p.id) AS tags"
            " FROM page p LEFT JOIN enrichment e ON e.page_id = p.id"
            " LEFT JOIN writeup w ON w.page_id = p.id AND w.superseded_at IS NULL"
            f" AND {roles.SHOWN.format(p='p')}"
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
