"""Claude's write-up of a board page (#256), as stored: its versions, the owner's
guidance, the board images it is made from, and the pages it links to. A topic page's
synthesis (#261, store.topics) is its write-up too, kept and shown the same way.

A write-up is derived data, never the page's text: one current version per page
(writeup_current), older ones kept, a regeneration or a restore inserting a new one.
These run on an open connection; the callers own the transaction.
"""

import json
import sqlite3
from typing import Any

from ..markdown import wiki_targets
from ..public import public_origins
from .roles import HAS_BOARD, IS_TOPIC, SHOWN, writeup_type


def _rows(conn: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, args)]  # below db: as db._rows


# A page's board images, in order (each distinct image file once): an image whose
# current reading says whiteboard or diagram (the photo call's kind, not the page's),
# unless that reading judged it a list of actions (a to-do sticky: it becomes a
# checklist instead). With what it read, and the JPEG photo ingest sent (if kept).
BOARD_IMAGES = """
WITH once AS (
    SELECT c.id AS capture_id, cb.sha256, c.received_at, cb.ord,
           row_number() OVER (PARTITION BY cb.sha256
                              ORDER BY c.received_at, c.id, cb.ord) AS copy
    FROM capture c JOIN capture_blob cb ON cb.capture_id = c.id
    JOIN blob b USING (sha256)
    WHERE c.page_id = :page AND b.mime LIKE 'image/%')
SELECT o.capture_id, o.sha256, json_extract(d.data, '$.kind') AS kind,
       d.text AS description, d.created_at AS read_at,
       (SELECT t.text FROM derived t WHERE t.capture_id = o.capture_id
          AND t.source_sha256 = o.sha256 AND t.kind = 'ocr'
          AND t.superseded_at IS NULL) AS text,
       r.sent_sha256 AS sent, r.image_width AS width, r.image_height AS height
FROM once o
JOIN derived d ON d.capture_id = o.capture_id AND d.source_sha256 = o.sha256
  AND d.kind = 'description' AND d.superseded_at IS NULL
LEFT JOIN model_run r ON r.id = d.run_id
WHERE o.copy = 1
  AND json_extract(d.data, '$.kind') IN ('whiteboard', 'diagram')
  AND coalesce(json_extract(r.output, '$.intent'), '') <> 'list-of-actions'
ORDER BY o.received_at, o.capture_id, o.ord
"""
# A board image of a page p read since its last write-up (or it has none)
READ_SINCE = """EXISTS (
    SELECT 1 FROM capture c JOIN derived d ON d.capture_id = c.id
    WHERE c.page_id = {p}.id AND d.kind = 'description' AND d.superseded_at IS NULL
      AND json_extract(d.data, '$.kind') IN ('whiteboard', 'diagram')
      AND d.created_at > coalesce(
        (SELECT max(w.created_at) FROM writeup w WHERE w.page_id = {p}.id), ''))"""
# A board page whose write-up is due: none of its photos waits or is being read, and
# a board image was read since its last write-up (or it has none)
DUE = f"""
SELECT 1 FROM page p WHERE p.id = :page AND p.deleted_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM job j JOIN capture c ON c.id = j.capture_id
                  WHERE c.page_id = p.id AND j.state IN ('queued', 'running'))
  AND {HAS_BOARD.format(p="p")}
  AND {READ_SINCE.format(p="p")}
"""
# A board page p (not a topic) whose current write-up is outdated (#262: is:outdated,
# the write-up view's outdated flag, scrap enrich --writeups --outdated; only a newly
# read photo regenerates one on its own, DUE): a board image read since it, or the
# page's text, title, kind or tags changed since, or made with another prompt version
# than {version} (a placeholder: ? or :version; NULL checks none), or whose text links a
# slug with no live page (in the trash or purged; undelete clears it, #310). Never
# one the owner restored: their Restore stands until they Regenerate (or a photo is
# read: DUE).
OUTDATED = f"""({HAS_BOARD} AND NOT {IS_TOPIC}
  AND EXISTS (SELECT 1 FROM writeup w WHERE w.page_id = {{p}}.id
    AND w.superseded_at IS NULL AND w.restored_from IS NULL
    AND (coalesce(w.prompt_version <> {{version}}, 0)
      OR w.created_at < max({{p}}.updated_at, coalesce((SELECT max(m.updated_at)
        FROM page_meta_rev m WHERE m.page_id = {{p}}.id), ''))
      OR {READ_SINCE}
      OR EXISTS (SELECT 1 FROM json_each(wiki_links(w.text)) l
        WHERE NOT EXISTS (SELECT 1 FROM page t
          WHERE t.slug = l.value AND t.deleted_at IS NULL)))))"""
COLUMNS = (
    "id, version, producer, run_id, prompt_version, summary, text, guidance,"
    " restored_from, superseded_at, created_at"
)
INSERT = """
INSERT INTO writeup (page_id, version, producer, run_id, prompt_version, summary, text,
                     guidance, restored_from, created_at)
VALUES (:page,
        (SELECT coalesce(max(version), 0) + 1 FROM writeup WHERE page_id = :page),
        :producer, :run, :prompt, :summary, :text, :guidance, :restored, :now)
RETURNING version
"""


def board_images(conn: sqlite3.Connection, page_id: str) -> list[dict[str, Any]]:
    """A page's board images in order (BOARD_IMAGES)."""
    return [dict(r) for r in conn.execute(BOARD_IMAGES, {"page": page_id})]


def due(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether a board page's write-up is due (DUE): all its photos read, and a board
    image read since its last one."""
    return conn.execute(DUE, {"page": page_id}).fetchone() is not None


def current(conn: sqlite3.Connection, page_id: str) -> dict[str, Any] | None:
    """A page's current write-up, or None (also before migration 12)."""
    try:
        row = conn.execute(
            f"SELECT {COLUMNS} FROM writeup"
            " WHERE page_id = ? AND superseded_at IS NULL",
            (page_id,),
        ).fetchone()
    except sqlite3.OperationalError:  # no such table: an older schema
        return None
    return dict(row) if row else None


def shown(conn: sqlite3.Connection, page_id: str) -> dict[str, Any] | None:
    """A page's current write-up while it is still a board page or a topic (its
    synthesis: roles.writeup_type), else None: one reprocessed into another kind keeps
    its versions as history, but they are no longer its summary, its search text, its
    links or on show."""
    up = current(conn, page_id)
    if up is None or writeup_type(conn, page_id) is None:
        return None
    return up


def versions(conn: sqlite3.Connection, page_id: str) -> list[dict[str, Any]]:
    """Every write-up of a page, newest first, each with current: whether it is."""
    rows = _rows(
        conn,
        f"SELECT {COLUMNS} FROM writeup WHERE page_id = ? ORDER BY version DESC",
        page_id,
    )
    return [{**r, "current": r["superseded_at"] is None} for r in rows]


def put(
    conn: sqlite3.Connection,
    page_id: str,
    stamp: str,
    *,
    producer: str,
    run_id: int | None,
    prompt_version: str,
    summary: str,
    text: str,
    guidance: str | None,
    restored_from: int | None = None,
) -> int:
    """Insert a page's new current write-up (the last one is superseded by a
    trigger); its version. The caller indexes the page again (index_page)."""
    return conn.execute(
        INSERT,
        {"page": page_id, "producer": producer, "run": run_id,
         "prompt": prompt_version, "summary": summary, "text": text,
         "guidance": guidance, "restored": restored_from, "now": stamp},
    ).fetchone()[0]  # fmt: skip


def guidance(conn: sqlite3.Connection, page_id: str) -> str | None:
    """The owner's guidance for a page's next write-up, if any."""
    try:
        row = conn.execute(
            "SELECT text FROM writeup_guidance WHERE page_id = ?", (page_id,)
        ).fetchone()
    except sqlite3.OperationalError:  # no such table: an older schema
        return None
    return row[0] if row else None


def set_guidance(
    conn: sqlite3.Connection, page_id: str, text: str | None, author: str, stamp: str
) -> None:
    """Keep the owner's guidance for a page's next write-up; empty or None: none."""
    if text is None or not text.strip():
        conn.execute("DELETE FROM writeup_guidance WHERE page_id = ?", (page_id,))
        return
    conn.execute(
        "INSERT INTO writeup_guidance VALUES (?, ?, ?, ?) ON CONFLICT (page_id)"
        " DO UPDATE SET text = excluded.text, author = excluded.author,"
        " updated_at = excluded.updated_at",
        (page_id, text.strip(), author, stamp),
    )


def links(conn: sqlite3.Connection, page_id: str) -> list[dict[str, str]]:
    """The pages (not in the trash) a page's current write-up links to, in order,
    while it is on show (a board page's, or a topic's synthesis)."""
    up = shown(conn, page_id)
    if up is None:
        return []
    slugs = wiki_targets(up["text"], public_origins())
    found = {
        r["slug"]: r
        for r in _rows(
            conn,
            "SELECT id, slug, title, kind FROM page WHERE deleted_at IS NULL"
            " AND id <> ? AND slug IN (SELECT value FROM json_each(?))",
            page_id, json.dumps(slugs),
        )
    }  # fmt: skip
    return [found[s] for s in slugs if s in found]


def backlinks(conn: sqlite3.Connection, slug: str) -> list[dict[str, str]]:
    """The pages (not in the trash, still board pages or topics) whose current
    write-up links to slug (SQL wiki_links). Only write-ups holding the slug as typed
    are parsed (instr): one escaped (`&#97;`, `\\-`) is missed, as in
    Store.backlinks."""
    try:
        return _rows(
            conn,
            "SELECT p.id, p.slug, p.title, p.kind FROM writeup w"
            " JOIN page p ON p.id = w.page_id WHERE w.superseded_at IS NULL"
            f" AND p.deleted_at IS NULL AND {SHOWN.format(p='p')} AND p.slug <> ?"
            " AND instr(w.text, ?) > 0 AND EXISTS (SELECT 1 FROM"
            " json_each(wiki_links(w.text)) l WHERE l.value = ?)"
            " ORDER BY w.created_at DESC",
            slug, slug, slug,
        )  # fmt: skip
    except sqlite3.OperationalError:  # no such table: an older schema
        return []


def outdated(conn: sqlite3.Connection, page_id: str, version: str | None) -> bool:
    """Whether a board page's current write-up is outdated (OUTDATED), version the
    current prompt's (None: not checked)."""
    sql = f"SELECT {OUTDATED.format(p='p', version='?')} FROM page p WHERE p.id = ?"
    row = conn.execute(sql, (version, page_id)).fetchone()
    return bool(row and row[0])


def view(
    conn: sqlite3.Connection,
    page_id: str,
    on: bool,
    stamp: str,
    version: str | None = None,
) -> dict[str, Any] | None:
    """A page's write-up as the page shows it, None unless it is a board page or a
    topic (a page that is no longer a board keeps its versions, unseen): board and
    topic (which it is), enrich on, the owner's guidance, the state of a write-up
    queued or being made (its latest write-up, topic or Ask job's), how many
    versions, outdated (a board's current write-up is: OUTDATED, version the current
    prompt's; a topic's synthesis is never said to be, the weekly pass remakes it),
    and the current one, with links: the slugs of the pages (not in the trash) it
    links to."""
    kind = writeup_type(conn, page_id)
    if kind is None:
        return None
    board, topic = kind == "board", kind == "topic"
    up = current(conn, page_id)
    job = conn.execute(
        "SELECT state, reason, last_error,"
        " (SELECT paused_until > ? FROM queue_state) AS paused"
        " FROM enrich_job WHERE page_id = ? AND reason IN ('writeup', 'ask', 'topic')"
        " ORDER BY id DESC LIMIT 1",
        (stamp, page_id),
    ).fetchone()
    state = None
    if job is not None:
        state = {"running": "processing", "dead": "failed"}.get(
            job["state"], job["state"]
        )
        if state == "queued" and job["paused"] and on:
            state = "paused"
    count = conn.execute(
        "SELECT count(*) FROM writeup WHERE page_id = ?", (page_id,)
    ).fetchone()[0]
    shown = ("version", "producer", "created_at", "prompt_version", "summary", "text",
             "guidance", "restored_from")  # fmt: skip
    return {
        "board": board,
        "topic": topic,
        "on": on,
        "guidance": guidance(conn, page_id),
        "state": state,
        "error": job["last_error"] if job is not None and state == "failed" else None,
        "versions": count,
        "outdated": board and outdated(conn, page_id, version),
        # with the pages it links that exist: the PWA links no other
        "current": up
        and {
            **{k: up[k] for k in shown},
            "links": [p["slug"] for p in links(conn, page_id)],
        },
    }
