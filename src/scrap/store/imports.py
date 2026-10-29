"""Importing pages (scrap import, Settings > Import Markdown): a page made elsewhere,
saved whole with its own slug, kind, fields, tags and dates."""

import json
from collections.abc import Sequence
from typing import Any

from .capture import _new_todo
from .constants import ENQUEUE, REV_INSERT, BlobRef
from .core import Core
from .db import transaction
from .helpers import check_value, new_ulid, now, todo_columns
from .indexing import enrich_on, queue_enrich
from .roles import should_enrich

# What an import may say made a page: a topic page or gc's review page is scrap's own,
# made again here, never imported
IMPORTED_BY = ("human", "claude")


class ImportMixin(Core):
    def import_page(
        self,
        p: dict[str, Any],
        captures: Sequence[tuple[str, str, str | None, Sequence[BlobRef]]],
        author: str,
        photos: bool = False,
        files: bool = True,
        enrich: bool = False,
    ) -> tuple[str, bool, bool]:
        """Save a page made elsewhere (captures of source 'import') with its own slug,
        kind, fields, tags and dates: p has slug, title, body, kind, fields, tags,
        created_at and updated_at, and may have id (the page's, kept) and made_by
        (human or claude). captures are (id, kind, text, blobs), blobs (sha, mime,
        size, name) already in files/; the first id is the retry key, as for a
        capture. A page whose id or first capture is here already (in the trash too)
        is left as it is: nothing is overwritten.

        Its photos are queued for Claude only with photos (a photo capture's images),
        its PDFs and text files are read locally (free) with files, and with enrich
        (and enrich on) a page enrich reads gets its enrich job now (reason backfill:
        an import has its own tag, so backfill() would pass it by).

        Returns its slug (another if that one was taken meanwhile), whether it is
        new, and whether its enrich job was queued."""
        for name, value in p["fields"].items():
            check_value(name, value)
        made_by = p.get("made_by") or "human"
        if made_by not in IMPORTED_BY:
            raise ValueError(f"made_by {made_by!r}")
        stamp = now()
        with self.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT p.slug FROM capture c JOIN page p ON p.id = c.page_id"
                " WHERE c.id = ?",
                (captures[0][0],),
            ).fetchone()
            if row is None and p.get("id"):
                row = conn.execute(
                    "SELECT slug FROM page WHERE id = ?", (p["id"],)
                ).fetchone()
            if row:
                return row[0], False, False
            blobs = [b for *_, bs in captures for b in bs]
            conn.executemany(
                "INSERT INTO blob VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                [(sha, mime, size, stamp) for sha, mime, size, _ in blobs],
            )
            page_id = p.get("id") or new_ulid()
            slug = p["slug"]
            if conn.execute("SELECT 1 FROM page WHERE slug = ?", (slug,)).fetchone():
                slug = self._slug(conn, slug)  # taken since it was planned
            todo, fields = todo_columns(p["kind"], p["fields"])
            conn.execute(
                "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
                " created_at, updated_at, made_by)"
                " VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (page_id, slug, p["title"], p["body"], p["kind"],
                 json.dumps(fields), p["created_at"], p["updated_at"], made_by),
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
                if photos if kind == "photo" else files:
                    conn.execute(ENQUEUE, {"capture": cid, "photo": None,
                                           "options": "{}", "now": stamp})  # fmt: skip
            conn.executemany(
                "INSERT INTO tag VALUES (?, ?)", [(page_id, t) for t in p["tags"]]
            )
            self._body(conn, page_id, follow=False)  # counted; kind and status kept
            self.reindex(conn, page_id)
            queued = enrich and enrich_on() and should_enrich(conn, page_id)
            if queued:
                queue_enrich(conn, page_id, "backfill")
            return slug, True, queued
