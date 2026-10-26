"""Capturing, reading and writing pages."""

import json
import sqlite3
from datetime import datetime
from typing import Any

from ..markdown import tasks
from .constants import (
    ALL_KINDS,
    BARE_URL,
    ENQUEUE,
    HEADING,
    HINTS,
    KINDS,
    KINDS_SHOWN,
    MAX_FIELDS,
    MAX_TAGS,
    MCP,
    SHA256,
    SOURCES,
    THUMB,
    TODO,
    ULID,
    BlobRef,
    Value,
)
from .core import Core
from .db import _rows, transaction
from .errors import ConflictError, InvalidError, NotFoundError
from .helpers import (
    _text,
    body_refs,
    boxes_before,
    check_page,
    check_todo,
    check_value,
    clean_tags,
    embeds,
    fields_for,
    lines,
    new_ulid,
    now,
    todo_columns,
    todo_only,
    too_big,
)
from .indexing import debounce, enrich_on, queue_enrich, should_enrich
from .topics import is_topic, key_of, of_page
from .topics import sources as topic_sources
from .writeups import backlinks as writeup_backlinks
from .writeups import links as writeup_links
from .writeups import view as writeup_view


class PagesMixin(Core):
    def prepare(self, data: dict[str, Any], mimes: list[str]) -> dict[str, Any]:
        """Check a capture request (before any file is written) and derive its page.

        mimes are the types of its files, if any.
        """
        cid = (_text(data, "id") or "").upper()
        if not ULID.fullmatch(cid):
            raise InvalidError("id must be a ULID")
        text = _text(data, "text", indent=True)
        url, hint = _text(data, "url"), _text(data, "hint")
        kind = _text(data, "kind")
        source = _text(data, "source") or "pwa"
        created = _text(data, "created_at") or now()
        try:
            when = datetime.fromisoformat(created)
        except ValueError:
            raise InvalidError("created_at must be ISO 8601") from None
        if source not in SOURCES:
            raise InvalidError(f"source must be one of {SOURCES}")
        if hint not in (None, *HINTS):
            raise InvalidError(f"hint must be one of {HINTS}")
        if kind not in (None, *KINDS):
            raise InvalidError(f"kind must be one of {KINDS}")
        kind = kind or hint
        todo = {k: check_todo(k, _text(data, k)) for k in TODO}
        if kind != "todo" and any(todo.values()):
            raise InvalidError("due and priority are for todos")
        if not url and text and BARE_URL.fullmatch(text.strip()):
            url, text = text.strip(), None  # a link shared as text
        if mimes:
            images = all(mime.startswith("image/") for mime in mimes)
            what = "photo" if images else "file"
        else:
            what = "url" if url else "note"
        if what == "note" and not text:
            raise InvalidError("empty capture")
        tags = data.get("tags")
        if tags is None:  # only missing or null means none: "" or {} is refused below
            tags = []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise InvalidError("tags must be a list of strings")
        tags = clean_tags(tags)  # as an edit's
        # Its first line without a heading's #s ("# Trip notes" is titled Trip notes)
        first = text.splitlines()[0] if text else ""
        title = (HEADING.sub("", first).strip() or first)[:200] if text else url
        return {
            "id": cid, "kind": what, "text": text, "url": url, "source": source,
            "created_at": created, "page_kind": kind, "fields": fields_for(kind, url),
            **todo,
            "title": title or when.strftime("%Y-%m-%d %H:%M"),
            "body": check_page("\n\n".join(x for x in (url, text) if x)),
            "tags": tags,
        }  # fmt: skip

    def capture(
        self,
        c: dict[str, Any],
        blobs: list[tuple[str, str, int, str | None]],
        author: str,
        tags: list[str] | None = None,
    ) -> tuple[dict[str, str], bool]:
        """Save a prepared capture as a new page, with these tags (else the
        capture's own, if any). Returns its reference and whether it is new. blobs
        are (sha256, mime, size, filename), already in files/.
        """
        cid, title, body, kind = c["id"], c["title"], c["body"], c["page_kind"]
        tags = c.get("tags") if tags is None else tags
        body = check_page("\n\n".join(x for x in (body, *embeds(blobs, body)) if x))
        stamp = now()
        with self.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT page_id FROM capture WHERE id = ?", (cid,)
            ).fetchone()
            if row:
                return self._ref(conn, cid, row[0]), False
            conn.executemany(
                "INSERT INTO blob VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                [(sha, mime, size, stamp) for sha, mime, size, _ in blobs],
            )
            page_id = new_ulid()
            conn.execute(
                "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
                " created_at, updated_at, due, priority, snoozed_until)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (page_id, self._slug(conn, title), title, body, kind or "note",
                 int(bool(kind)), json.dumps(c["fields"]), stamp, stamp,
                 c.get("due"), c.get("priority"), c.get("snoozed_until")),
            )  # fmt: skip
            conn.execute(
                "INSERT INTO page_rev VALUES (?, 1, ?, ?, ?, ?)",
                (page_id, title, body, author, stamp),
            )
            conn.execute(
                "INSERT INTO capture VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, c["kind"], c["text"], c["url"], c["source"], author,
                 c["created_at"], stamp, page_id),
            )  # fmt: skip
            conn.executemany(
                "INSERT INTO capture_blob VALUES (?, ?, ?, ?)",
                [(cid, i, sha, name) for i, (sha, _, _, name) in enumerate(blobs)],
            )
            conn.executemany(
                "INSERT INTO tag VALUES (?, ?)", [(page_id, t) for t in tags or []]
            )
            self._body(conn, page_id)
            self.reindex(conn, page_id)
            conn.execute(ENQUEUE, {"capture": cid, "photo": None, "options": "{}",
                                   "now": stamp})  # fmt: skip
            if (
                enrich_on()
                and c["kind"] in ("note", "url")  # a photo has ingest
                and should_enrich(conn, page_id)
            ):
                # A link is fetched at once; a note waits, in case it is edited now
                wait = 0.0 if c["kind"] == "url" else debounce()
                queue_enrich(conn, page_id, "capture", wait)
            return self._ref(conn, cid, page_id), True

    def import_page(
        self,
        p: dict[str, Any],
        captures: list[tuple[str, str, str | None, list[BlobRef]]],
        author: str,
        enqueue: bool = False,
    ) -> tuple[str, bool]:
        """Save a page made elsewhere (scrap import) with its own slug, kind, fields,
        tags and dates. captures are (id, kind, text, blobs), blobs already in files/;
        the first id is the retry key, as for a capture. Its text, the original, also
        keeps ingest from retitling the page. Returns the slug and whether it is new.
        enqueue: send its photos to Claude, as a capture would.
        """
        for name, value in p["fields"].items():
            check_value(name, value)
        stamp = now()
        with self.connect() as conn, transaction(conn):
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
            conn.execute(
                "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
                " created_at, updated_at, due, priority, snoozed_until)"
                " VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
                (page_id, p["slug"], p["title"], p["body"], p["kind"],
                 json.dumps(fields), p["created_at"], p["updated_at"], todo["due"],
                 todo["priority"], todo["snoozed_until"]),
            )  # fmt: skip
            conn.execute(
                "INSERT INTO page_rev VALUES (?, 1, ?, ?, ?, ?)",
                (page_id, p["title"], p["body"], author, p["updated_at"]),
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
            self._body(
                conn, page_id, follow=False
            )  # counted; its kind and status as it was
            self.reindex(conn, page_id)
            return p["slug"], True

    def recent(self, limit: int, kind: str | None = None) -> list[dict[str, Any]]:
        """Pages, newest change first; only those of one kind, if given."""
        if kind not in (None, *ALL_KINDS):
            raise InvalidError(f"kind must be one of {ALL_KINDS}")
        with self.connect() as conn:
            rows = _rows(
                conn,
                "SELECT id, slug, title, kind, kind_fixed, fields, created_at,"
                f" updated_at, due, priority, snoozed_until, task_done, task_total,"
                f" {THUMB} AS thumb"
                " FROM page p WHERE deleted_at IS NULL"
                " AND coalesce(?, kind) = kind"
                " ORDER BY updated_at DESC, id DESC LIMIT ?",
                kind, limit,
            )  # fmt: skip
        return [todo_only({**r, "fields": json.loads(r["fields"])}) for r in rows]

    def page(self, key: str, trashed: bool = False) -> dict[str, Any]:
        """A page with its current revision and its captures and their blobs. With
        trashed, one in the trash too, with its deleted_at (None for any other)."""
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
        for c in captures:
            c["blobs"] = _rows(
                conn,
                "SELECT b.sha256, b.mime, b.size, cb.filename FROM capture_blob cb"
                " JOIN blob b USING (sha256) WHERE capture_id = ? ORDER BY ord",
                c["id"],
            )
            for blob in c["blobs"]:
                blob["ingest"] = self._ingest(conn, c["id"], blob["sha256"])
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
        return todo_only({**page, "fields": fields, "tags": tags, "captures": captures,
                          "removed": removed, **extra})  # fmt: skip

    def _enriched(
        self, conn: sqlite3.Connection, page_id: str, slug: str
    ) -> dict[str, Any]:
        """What Claude added to a page apart from its text: model_tags (the page's
        tags Claude added), related (Claude's picks, pages that picked this one,
        pages linking here with [[slug]], and pages its write-up links to or whose
        write-up links here, each once, with via: claude, link or both, writeup, or
        topic for a topic's synthesis citing a page, either way), enrich (its job's
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
        self, conn: sqlite3.Connection, cid: str, sha: str
    ) -> dict[str, Any] | None:
        """A photo's ingest state and current results; None if it was never queued."""
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

    def update_page(
        self,
        key: str,
        base_rev: int | None,
        title: str | None,
        body: str | None,
        author: str,
        kind: str | None = None,
        fields: dict[str, Value | None] | None = None,
        tags: list[str] | None = None,
        todo: dict[str, str | None] | None = None,
        source: str = "web",
        tags_shown: list[str] | None = None,
    ) -> dict[str, Any]:
        """Change a page's title and/or body, refusing an edit of a stale revision;
        and/or its kind (the user's choice, which ingest then keeps), fields and tags
        (all of them: these replace the page's); and/or a todo's due date and priority
        (those given; None clears one). A change of kind or tags is a metadata
        revision (page_meta_rev) by author from source. tags_shown, if given, are the
        tags the editor started from: a tag Claude added since (not among them) is
        kept, not retired."""
        if kind not in (None, *KINDS):
            raise InvalidError(f"kind must be one of {KINDS}")
        tags = None if tags is None else clean_tags(tags)
        shown = None if tags_shown is None else clean_tags(tags_shown)
        todo = {k: check_todo(k, v) for k, v in (todo or {}).items() if k in TODO}
        with self.connect() as conn, transaction(conn):
            page = self._page_row(conn, key)
            before = self._meta(conn, page["id"])
            if kind is not None or fields:
                self._set_kind(conn, page, kind, fields or {})
            if todo:  # as status: not a revision, nor a change to updated_at
                self._set_todo(conn, page["id"], kind or page["kind"], todo)
            if tags is not None:  # not a revision, nor a change to updated_at
                spare: list[str] = []  # Claude's, kept but past MAX_TAGS: not retired
                if shown is not None:  # Claude's tags added after the editor opened
                    tags += self._model_tags_since(conn, page["id"], shown + tags)
                    tags, spare = tags[:MAX_TAGS], tags[MAX_TAGS:]
                conn.execute("DELETE FROM tag WHERE page_id = ?", (page["id"],))
                conn.executemany(
                    "INSERT INTO tag VALUES (?, ?)", [(page["id"], t) for t in tags]
                )
                self._model_tags(conn, page["id"], tags, spare)
            if tags is not None or (fields and "summary" in fields):  # indexed
                self.reindex(conn, page["id"])
            if kind is not None or tags is not None:  # before text: see _record_meta
                after = self._meta(conn, page["id"])
                now_fields = json.loads(conn.execute(
                    "SELECT fields FROM page WHERE id = ?", (page["id"],)
                ).fetchone()[0])  # fmt: skip
                was, sent = json.loads(page["fields"]), fields or {}
                added = {
                    k: v
                    for k, v in now_fields.items()
                    if k not in was and k not in sent
                }  # a new kind's defaults
                self._record_meta(
                    conn, page["id"], author, source, before, after, added
                )
            if title is None and body is None:
                return self.page_in(conn, page["id"])
            if page["rev"] != base_rev:
                raise ConflictError(page["rev"])
            if (
                title is not None
                and " ".join(title.split())
                == conn.execute(
                    "SELECT title FROM page_rev WHERE page_id = ? AND rev = ?",
                    (page["id"], base_rev),
                ).fetchone()[0]
            ):
                title = None  # unchanged since base_rev: keep a newer (model) title
            new_title = page["title"] if title is None else " ".join(title.split())
            new_body: str = (
                page["body"] if body is None else check_page(lines(body), page["body"])
            )
            if not new_title:
                raise InvalidError("title must not be empty")
            if (new_title, new_body) != (page["title"], page["body"]):
                stamp = now()
                conn.execute(
                    "UPDATE page SET title = ?, body = ?, updated_at = ? WHERE id = ?",
                    (new_title, new_body, stamp, page["id"]),
                )
                conn.execute(
                    "INSERT INTO page_rev VALUES (?, ?, ?, ?, ?, ?)",
                    (page["id"], page["rev"] + 1, new_title, new_body, author, stamp),
                )
                self._body(
                    conn,
                    page["id"],
                    boxes_before(page),
                    status_set=bool(fields and "status" in fields),
                )
                self.reindex(conn, page["id"])
                if enrich_on() and should_enrich(
                    conn, page["id"]
                ):  # again once edits stop
                    queue_enrich(conn, page["id"], "save", debounce())
            return self.page_in(conn, page["id"])

    def _model_tags_since(
        self, conn: sqlite3.Connection, page_id: str, known: list[str]
    ) -> list[str]:
        """The page's tags from Claude, 'on', that are not in known: added while a tag
        editor that did not show them was open (so the user has not taken them off)."""
        return [r[0] for r in conn.execute(
            "SELECT m.tag FROM model_tag m JOIN tag t USING (page_id, tag)"
            " WHERE m.page_id = ? AND m.state = 'on'"
            " AND m.tag NOT IN (SELECT value FROM json_each(?)) ORDER BY t.rowid",
            (page_id, json.dumps(known)),
        )]  # fmt: skip

    def _model_tags(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        tags: list[str],
        spare: list[str] | None = None,
    ) -> None:
        """After the user set a page's tags: a tag of Claude's they took off is 'off'
        (Claude never adds it back), one in spare (not taken off, just no room) is
        not; one they put back is theirs from now on."""
        conn.execute(
            "UPDATE model_tag SET state = 'off' WHERE page_id = ? AND state = 'on'"
            " AND tag NOT IN (SELECT value FROM json_each(?))",
            (page_id, json.dumps([*tags, *(spare or [])])),
        )
        conn.execute(
            "DELETE FROM model_tag WHERE page_id = ? AND state = 'off'"
            " AND tag IN (SELECT value FROM json_each(?))",
            (page_id, json.dumps(tags)),
        )

    def _body(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        before: tuple[int, int] = (0, 0),
        follow: bool = True,
        status_set: bool = False,
    ) -> None:
        """After a page's text is written (before: its task boxes, ticked and in
        all, as they were: boxes_before): its boxes counted. With follow, a note
        nobody filed (kind_fixed 0) that has boxes becomes a todo, and a todo's
        status follows them: all ticked, when they were not, is done; one unticked,
        or a new unticked one, when all were reopens a done one. Ticking a page done
        by hand changes no box, a cancelled one is left as it is, a status set in
        the same edit (status_set) wins, and none of it is a revision."""
        row = conn.execute(
            "SELECT body, kind, kind_fixed, fields FROM page WHERE id = ?", (page_id,)
        ).fetchone()
        done, total = tasks(row["body"])
        conn.execute(
            "UPDATE page SET task_done = ?, task_total = ? WHERE id = ?",
            (done, total, page_id),
        )
        if not follow or not total:
            return
        kind, fields = row["kind"], json.loads(row["fields"])
        if kind == "note" and not row["kind_fixed"]:  # filed by its boxes, not fixed
            kind, fields = "todo", {**fields_for("todo", None), **fields}
        if kind != "todo":
            return
        was_all = before[1] > 0 and before[0] == before[1]
        status = fields.get("status", "open")
        if status_set:  # the user's own, in this edit: the boxes don't override it
            pass
        elif done == total and not was_all and status not in ("done", "cancelled"):
            fields["status"] = "done"
        elif was_all and done < total and status == "done":
            fields["status"] = "open"
        conn.execute(
            "UPDATE page SET kind = ?, fields = ? WHERE id = ?",
            (kind, json.dumps(fields), page_id),
        )

    def _set_kind(
        self,
        conn: sqlite3.Connection,
        page: sqlite3.Row,
        kind: str | None,
        changes: dict[str, Value | None],
    ) -> None:
        """A kind the user chose, fixed so ingest never changes it. A new kind keeps
        every field the page has (a summary, a due date, an imported status: a stray
        tap must lose nothing) and adds its defaults for those it lacks. Then changes to
        the fields (None drops one), at most MAX_FIELDS in all. Neither is a new
        revision, nor moves the page up the recent list."""
        fields = json.loads(page["fields"])
        for name, value in changes.items():
            check_value(name, value)
            if value is None:
                fields.pop(name, None)
            else:
                fields[name] = value
        if len(fields) > MAX_FIELDS:
            raise InvalidError(f"a page has at most {MAX_FIELDS} fields")
        if kind is not None and kind != page["kind"]:
            url = conn.execute(
                "SELECT url FROM capture WHERE page_id = ? AND url IS NOT NULL"
                " ORDER BY received_at LIMIT 1",
                (page["id"],),
            ).fetchone()
            # only defaults the page lacks and has room for: never at the cost of a
            # field it has, nor one this request just dropped
            for name, value in fields_for(kind, url and url[0]).items():
                if name not in fields and name not in changes:
                    if len(fields) < MAX_FIELDS:
                        fields[name] = value
        conn.execute(
            "UPDATE page SET kind = ?, kind_fixed = ?, fields = ? WHERE id = ?",
            (kind or page["kind"], int(kind is not None or page["kind_fixed"]),
             json.dumps(fields), page["id"]),
        )  # fmt: skip

    def _set_todo(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        kind: str,
        todo: dict[str, str | None],
    ) -> None:
        """Set (or clear, None) a todo's due date and/or priority, checked already."""
        if kind != "todo" and any(v is not None for v in todo.values()):
            raise InvalidError("due and priority are for todos")
        sets = ", ".join(f"{k} = ?" for k in todo)  # names from TODO only
        conn.execute(f"UPDATE page SET {sets} WHERE id = ?", (*todo.values(), page_id))

    def append(
        self,
        key: str,
        cid: str,
        text: str,
        author: str,
        tags: list[str],
        most: int,
        todo: dict[str, str | None] | None = None,
    ) -> tuple[dict[str, str], bool]:
        """Add text (a capture with id cid, source mcp) to the end of a page Claude
        wrote, and these tags, and set its due date and priority (a todo's; those
        given, None clearing one); a retry with the same cid changes nothing. The
        page's body is then at most most bytes. Returns its reference and whether it
        is new."""
        todo = {k: check_todo(k, v) for k, v in (todo or {}).items() if k in TODO}
        stamp = now()
        with self.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT page_id FROM capture WHERE id = ?", (cid,)
            ).fetchone()
            if row:
                return self._ref(conn, cid, row[0]), False
            page = self._page_row(conn, key)
            if not self.by_claude(conn, page["id"]):
                raise InvalidError("only a page written over MCP can be appended to")
            before = self._meta(conn, page["id"])
            if todo:
                self._set_todo(conn, page["id"], page["kind"], todo)
            body = "\n\n".join(x for x in (page["body"].rstrip(), text) if x)
            if len(body.encode()) > most:
                raise InvalidError(too_big(len(body.encode()), most))
            if text:  # none: only its due date or priority changed (no revision)
                conn.execute(
                    "UPDATE page SET body = ?, updated_at = ? WHERE id = ?",
                    (body, stamp, page["id"]),
                )
                conn.execute(
                    "INSERT INTO page_rev VALUES (?, ?, ?, ?, ?, ?)",
                    (page["id"], page["rev"] + 1, page["title"], body, author, stamp),
                )
                self._body(conn, page["id"], boxes_before(page))
                if enrich_on() and should_enrich(conn, page["id"]):  # as for a save
                    queue_enrich(conn, page["id"], "save", debounce())
            conn.execute(  # the retry key, even with no text
                "INSERT INTO capture VALUES (?, 'note', ?, NULL, ?, ?, ?, ?, ?)",
                (cid, text or None, MCP, author, stamp, stamp, page["id"]),
            )
            conn.executemany(
                "INSERT INTO tag VALUES (?, ?) ON CONFLICT DO NOTHING",
                [(page["id"], t) for t in tags],
            )
            # Its tags, as a revision; not a kind its new task boxes filed it as
            after = before._replace(tags=sorted({*before.tags, *tags}))
            self._record_meta(conn, page["id"], author, MCP, before, after)
            self.reindex(conn, page["id"])
            return self._ref(conn, cid, page["id"]), True
