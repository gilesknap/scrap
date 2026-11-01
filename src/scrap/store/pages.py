"""Reading pages: the recent list, one page with its captures and what Claude
added, and the files they show."""

import json
import sqlite3
from typing import Any

from .constants import KINDS, KINDS_SHOWN, SHA256, THUMB
from .core import Core
from .db import _rows
from .errors import InvalidError, NotFoundError
from .guidance import of_page as image_guidance
from .helpers import body_refs, file_kind, now, todo_only
from .indexing import enrich_on
from .roles import is_topic, made_by
from .titles import titles
from .todo import cols as todo_cols
from .topics import key_of, of_page
from .topics import sources as topic_sources
from .writeups import backlinks as writeup_backlinks
from .writeups import links as writeup_links
from .writeups import view as writeup_view


class PagesMixin(Core):
    def recent(self, limit: int, kind: str | None = None) -> list[dict[str, Any]]:
        """Pages, newest change first; only those of one kind, if given."""
        if kind not in (None, *KINDS):
            raise InvalidError(f"kind must be one of {KINDS}")
        with self.connect() as conn:
            rows = _rows(
                conn,
                "SELECT id, slug, title, kind, kind_fixed, fields, created_at,"
                f" updated_at, {todo_cols('p')}, task_done, task_total,"
                f" {THUMB} AS thumb"
                " FROM page p WHERE deleted_at IS NULL"
                " AND coalesce(?, kind) = kind"
                " ORDER BY updated_at DESC, id DESC LIMIT ?",
                kind, limit,
            )  # fmt: skip
        return [todo_only({**r, "fields": json.loads(r["fields"])}) for r in rows]

    def page(self, key: str, trashed: bool = False) -> dict[str, Any]:
        """A page with its current revision, who made it (roles.made_by: human, claude,
        topic or gc) and its captures and their blobs. With trashed, one in the trash
        too, with its deleted_at (None for any other)."""
        with self.connect() as conn:
            return self.page_in(conn, key, trashed)

    def page_in(
        self, conn: sqlite3.Connection, key: str, trashed: bool = False
    ) -> dict[str, Any]:
        """page(), on an open connection (e.g. in the transaction that changed it)."""
        page = dict(self._page_row(conn, key, trashed))
        captures = _rows(
            conn,
            "SELECT id, kind, text, url, source, author, created_at,"
            " received_at FROM capture WHERE page_id = ? ORDER BY received_at",
            page["id"],
        )
        guided = image_guidance(conn, page["id"])  # the owner's, per image (#538)
        for c in captures:
            c["blobs"] = _rows(
                conn,
                "SELECT b.sha256, b.mime, b.size, cb.filename FROM capture_blob cb"
                " JOIN blob b USING (sha256) WHERE capture_id = ? ORDER BY ord",
                c["id"],
            )
            for blob in c["blobs"]:
                blob["ingest"] = self._ingest(
                    conn, c["id"], blob["sha256"], blob["mime"]
                )
                if blob["mime"].startswith("image/"):  # for its next reading
                    blob["guidance"] = guided.get((c["id"], blob["sha256"]))
        tags = [r[0] for r in conn.execute(
            "SELECT tag FROM tag WHERE page_id = ? ORDER BY"  # most used first
            " (SELECT count(*) FROM tag t WHERE t.tag = tag.tag) DESC, tag",
            (page["id"],),
        )]  # fmt: skip
        deleted_at = page.pop("deleted_at")
        if trashed:
            page["deleted_at"] = deleted_at
        fields = json.loads(page["fields"])
        removed = sorted(self.removed(conn, page["id"], page["body"]))
        extra = self._enriched(conn, page["id"], page["slug"])
        page["public"] = bool(page["public"])  # ADR 43: published_at is scrap.publish's
        return todo_only({**page, "fields": fields, "tags": tags, "captures": captures,
                          "made_by": made_by(conn, page["id"]),  # the PWA's badge
                          "removed": removed, **extra,
                          # its links' pages' titles, which a bare link shows (#508)
                          "titles": titles(conn, page["body"])})  # fmt: skip

    def _enriched(
        self, conn: sqlite3.Connection, page_id: str, slug: str
    ) -> dict[str, Any]:
        """What Claude added to a page apart from its text: model_tags (the page's
        tags Claude added), related (Claude's picks, pages that picked this one,
        pages linking here (backlinks: [[slug]] or its address), and pages its
        write-up links to or whose write-up links here, each once, with via: claude,
        link or both, writeup, or topic for a topic's synthesis citing a page, either
        way), enrich (its job's
        state and the summary), None if never asked and off, writeup (a board page's
        write-up or a topic's synthesis, writeups.view), topics (the topics it is a
        source of: id, slug, title) and topic (None, or for a topic page its key and
        its sources, those the owner excluded too)."""
        model_tags = [r[0] for r in conn.execute(
            "SELECT m.tag FROM model_tag m JOIN tag t USING (page_id, tag)"
            " WHERE m.page_id = ? AND m.state = 'on'", (page_id,),
        )]  # fmt: skip
        picks = _rows(
            conn,
            "SELECT p.id, p.slug, p.title, p.kind FROM ("
            " SELECT other_id AS id, rank FROM related WHERE page_id = ?"
            " UNION ALL SELECT page_id, rank + 100 FROM related WHERE other_id = ?"
            ") r JOIN page p ON p.id = r.id WHERE p.deleted_at IS NULL"
            " GROUP BY p.id ORDER BY min(r.rank) LIMIT 8",
            page_id,
            page_id,
        )
        related = {r["id"]: {**r, "via": "claude"} for r in picks}
        for b in self._backlinks(conn, slug):
            if b["id"] in related:
                related[b["id"]]["via"] = "both"
            else:
                related[b["id"]] = {**b, "via": "link"}
        # A topic first here, a board first in writeups.view (roles.writeup_type's TODO)
        topic = is_topic(conn, page_id)
        for w in writeup_links(conn, page_id):
            related.setdefault(w["id"], {**w, "via": "topic" if topic else "writeup"})
        for w in writeup_backlinks(conn, slug):
            via = "topic" if is_topic(conn, w["id"]) else "writeup"
            related.setdefault(w["id"], {**w, "via": via})
        job = conn.execute(
            "SELECT state, last_error, reason,"
            " (SELECT paused_until > :now FROM queue_state) AS paused,"
            " (SELECT reason FROM queue_state) AS pause_reason"
            " FROM enrich_job WHERE page_id = :page ORDER BY id DESC LIMIT 1",
            {"now": now(), "page": page_id},
        ).fetchone()
        done = conn.execute(
            "SELECT summary, producer, source, source_title, updated_at"
            " FROM enrichment WHERE page_id = ?",
            (page_id,),
        ).fetchone()
        enrich = None
        if job or done or enrich_on():
            state = job and {"running": "processing", "dead": "failed"}.get(
                job["state"], job["state"]
            )
            # the queue is shared with ingest; with Claude off nothing would resume
            held = state == "queued" and job["paused"] and enrich_on()
            if held:
                state = "paused"
            enrich = {
                "on": enrich_on(),
                "state": state,  # None: never queued
                "error": job and job["state"] == "dead" and job["last_error"] or None,
                "reason": job["pause_reason"] if held else None,  # why it is paused
                "summary": done and done["summary"] or None,
                "producer": done and done["producer"],
                "source": done and done["source"],
                "at": done and done["updated_at"],
            }
        return {"model_tags": model_tags, "related": list(related.values()),
                "enrich": enrich,
                "writeup": writeup_view(conn, page_id, enrich_on(), now(),
                                        self.prompts.get("writeup")),  # fmt: skip
                "topics": of_page(conn, page_id),
                "topic": {
                    "key": key_of(conn, page_id),
                    "sources": topic_sources(conn, page_id, excluded=True),
                } if topic else None}  # fmt: skip

    def removed(self, conn: sqlite3.Connection, page_id: str, body: str) -> set[str]:
        """The files an earlier revision of a page's text referred to and its text no
        longer does: their embeds were deleted, so the page no longer shows them (a
        photo of a page made before photos were embedded still is)."""
        earlier: set[str] = set()
        for (text,) in conn.execute(
            "SELECT body FROM page_rev WHERE page_id = ?", (page_id,)
        ):
            earlier |= body_refs(text)
        return earlier - body_refs(body)

    def blob_uses(self, sha: str, page: str) -> int:
        """How many pages other than page (an id) show a stored file, by its embed or
        as a file of their own; the trash left out. NotFoundError if not stored."""
        if not SHA256.fullmatch(sha):
            raise NotFoundError(sha)
        with self.connect() as conn:
            stored = "SELECT 1 FROM blob WHERE sha256 = ?"
            if not conn.execute(stored, (sha,)).fetchone():
                raise NotFoundError(sha)
            return conn.execute(
                "SELECT count(*) FROM page p WHERE p.deleted_at IS NULL AND p.id <> ?"
                " AND (instr(p.body, '/api/blobs/' || ?) OR EXISTS (SELECT 1 FROM"
                " capture c JOIN capture_blob cb ON cb.capture_id = c.id"
                " WHERE c.page_id = p.id AND cb.sha256 = ?))",
                (page, sha, sha),
            ).fetchone()[0]

    def _ingest(
        self, conn: sqlite3.Connection, cid: str, sha: str, mime: str
    ) -> dict[str, Any] | None:
        """A photo's ingest state and current results; None if it was never queued. A
        file's (a PDF's, a text file's: file_kind) is _file_ingest's."""
        kind = file_kind(mime)
        if kind:
            return self._file_ingest(conn, cid, sha, kind)
        job = conn.execute(
            "SELECT state, failures, last_error,"
            " (SELECT paused_until > ? FROM queue_state) AS paused"
            " FROM job WHERE capture_id = ? AND source_sha256 = ?"
            " ORDER BY id DESC LIMIT 1",
            (now(), cid, sha),
        ).fetchone()
        if job is None:
            return None
        state = {"running": "processing", "dead": "failed"}.get(job[0], job[0])
        if state == "queued" and job["paused"]:
            state = "paused"
        current = {
            row["kind"]: row
            for row in conn.execute(
                "SELECT id, kind, version, producer, text, data,"
                " json_extract(data, '$.width') AS width,"
                " json_extract(data, '$.height') AS height,"
                " json_array_length(data, '$.elements') AS element_count FROM derived"
                " WHERE capture_id = ? AND source_sha256 = ? AND superseded_at IS NULL",
                (cid, sha),
            )
        }
        ocr, about, drawing = (current.get(k) for k in KINDS_SHOWN)
        return {
            "state": state,
            "failures": job["failures"],
            "error": job["last_error"],
            "text": ocr and ocr["text"],
            "description": about and about["text"],
            "image_kind": about and json.loads(about["data"] or "{}").get("kind"),
            "drawing": drawing
            and {
                "id": drawing["id"],
                "version": drawing["version"],
                "producer": drawing["producer"],
                "width": drawing["width"],  # its frame: the photo as sent to Claude
                "height": drawing["height"],
                "element_count": drawing["element_count"],
            },
        }

    def _file_ingest(
        self, conn: sqlite3.Connection, cid: str, sha: str, kind: str
    ) -> dict[str, Any] | None:
        """A file's ingest (#234): state (queued, processing, done or failed; never
        paused: a pause does not hold a file), failures, error, kind (pdf or text),
        and from its current text (None until read): pages and pages_read (a PDF's),
        truncated, text_chars and searchable (it has text to find). The text itself
        is file_text's, not on every page read."""
        job = conn.execute(
            "SELECT state, failures, last_error FROM job"
            " WHERE capture_id = ? AND source_sha256 = ? ORDER BY id DESC LIMIT 1",
            (cid, sha),
        ).fetchone()
        if job is None:
            return None
        got = conn.execute(
            "SELECT data, coalesce(length(text), 0) FROM derived WHERE capture_id = ?"
            " AND source_sha256 = ? AND kind = 'ocr' AND superseded_at IS NULL",
            (cid, sha),
        ).fetchone()
        data = json.loads(got[0] or "{}") if got else {}
        return {
            "state": {"running": "processing", "dead": "failed"}.get(job[0], job[0]),
            "failures": job["failures"],
            "error": job["last_error"],
            "kind": kind,
            "pages": data.get("pages"),
            "pages_read": data.get("pages_read"),
            "truncated": bool(data.get("truncated")),
            "text_chars": got[1] if got else 0,
            "searchable": bool(got and got[1]),
        }

    def file_text(self, cid: str, sha: str, limit: int) -> tuple[str | None, bool]:
        """A file's current text (what ingest read from it), at most limit characters,
        and whether it was cut; None if it has none."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT substr(text, 1, ?), length(text) > ? FROM derived"
                " WHERE capture_id = ? AND source_sha256 = ? AND kind = 'ocr'"
                " AND superseded_at IS NULL",
                (limit, limit, cid, sha),
            ).fetchone()
        return (row[0], bool(row[1])) if row else (None, False)
