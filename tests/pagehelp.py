"""A test helper: a page written whole, as the removed importer wrote it (its dates,
kind fixed, captures with source 'import'), so tests can build pages of that shape,
which stores imported before the importer was removed still hold."""

import json
from collections.abc import Sequence
from typing import Any

from scrap.store import Store, new_ulid, now, transaction
from scrap.store.capture import _new_todo
from scrap.store.constants import ENQUEUE, REV_INSERT, BlobRef
from scrap.store.helpers import check_value, todo_columns


def import_page(
    store: Store,
    p: dict[str, Any],
    captures: Sequence[tuple[str, str, str | None, Sequence[BlobRef]]],
    author: str,
    enqueue: bool = False,
) -> tuple[str, bool]:
    """Save a page made elsewhere (an old import's shape, source 'import') with its
    own slug, kind, fields, tags and dates. captures are (id, kind, text, blobs),
    blobs (sha, mime, size, name) already in files/; the first id is the retry key.
    Returns the slug and whether it is new. enqueue: send its photos to Claude.
    """
    for name, value in p["fields"].items():
        check_value(name, value)
    stamp = now()
    with store.connect() as conn, transaction(conn):
        row = conn.execute(
            "SELECT p.slug FROM capture c JOIN page p ON p.id = c.page_id"
            " WHERE c.id = ?",
            (captures[0][0],),
        ).fetchone()
        if row:
            return row[0], False
        blobs = [b for *_, bs in captures for b in bs]
        conn.executemany(
            "INSERT INTO blob VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
            [(sha, mime, size, stamp) for sha, mime, size, _ in blobs],
        )
        page_id = new_ulid()
        todo, fields = todo_columns(p["kind"], p["fields"])
        conn.execute(  # made_by human: the owner's, made elsewhere
            "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
            " created_at, updated_at, made_by)"
            " VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'human')",
            (page_id, p["slug"], p["title"], p["body"], p["kind"],
             json.dumps(fields), p["created_at"], p["updated_at"]),
        )  # fmt: skip
        _new_todo(conn, page_id, todo)
        conn.execute(
            REV_INSERT,
            (page_id, 1, p["title"], p["body"], author, "web", p["updated_at"]),
        )
        for cid, kind, text, bs in captures:
            conn.execute(
                "INSERT INTO capture VALUES (?, ?, ?, NULL, 'import', ?, ?, ?, ?)",
                (cid, kind, text, author, p["created_at"], stamp, page_id),
            )
            conn.executemany(
                "INSERT INTO capture_blob VALUES (?, ?, ?, ?)",
                [(cid, i, sha, name) for i, (sha, _, _, name) in enumerate(bs)],
            )
            if enqueue:
                conn.execute(ENQUEUE, {"capture": cid, "photo": None,
                                       "options": "{}", "now": stamp})  # fmt: skip
        conn.executemany(
            "INSERT INTO tag VALUES (?, ?)", [(page_id, t) for t in p["tags"]]
        )
        store._body(
            conn, page_id, follow=False
        )  # counted; its kind and status as it was
        store.reindex(conn, page_id)
        return p["slug"], True
