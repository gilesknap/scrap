"""Capturing pages: a new capture, an imported page, text appended to Claude's."""

import json
import sqlite3
from datetime import datetime
from typing import Any

from .constants import (
    BARE_URL,
    ENQUEUE,
    HEADING,
    HINTS,
    KINDS,
    MCP,
    REV_INSERT,
    SOURCES,
    TODO,
    ULID,
    BlobRef,
)
from .core import Core
from .db import transaction
from .errors import InvalidError
from .helpers import (
    _text,
    boxes_before,
    check_page,
    check_todo,
    check_value,
    clean_tags,
    embeds,
    fields_for,
    new_ulid,
    now,
    todo_columns,
    too_big,
)
from .indexing import debounce, enrich_on, queue_enrich
from .roles import by_claude, by_ingest, made_by_source, should_enrich
from .todo import write as write_todo


def _new_todo(
    conn: sqlite3.Connection, page_id: str, todo: dict[str, str | None]
) -> None:
    """A new page's todo values, if it has any."""
    if any(v is not None for v in todo.values()):
        write_todo(conn, page_id, todo)


class CaptureMixin(Core):
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
            # A photo capture if any is an image, as Add photo's (store.photos): its
            # images go to Claude; a PDF or text file among them is still read (ENQUEUE)
            images = any(mime.startswith("image/") for mime in mimes)
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
            conn.execute(  # made_by: by its source, once (roles.made_by_source)
                "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
                " created_at, updated_at, made_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (page_id, self._slug(conn, title), title, body, kind or "note",
                 int(bool(kind)), json.dumps(c["fields"]), stamp, stamp,
                 made_by_source(c["source"])),
            )  # fmt: skip
            _new_todo(conn, page_id, {n: c.get(n) for n in TODO})
            conn.execute(
                REV_INSERT,
                (page_id, 1, title, body, author,
                 MCP if c["source"] == MCP else "web", stamp),
            )  # fmt: skip
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
                and not by_ingest(c["kind"])  # a photo or file has ingest
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
            self._body(
                conn, page_id, follow=False
            )  # counted; its kind and status as it was
            self.reindex(conn, page_id)
            return p["slug"], True

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
            if not by_claude(conn, page["id"]):
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
                    REV_INSERT,
                    (page["id"], page["rev"] + 1, page["title"], body, author, MCP,
                     stamp),
                )  # fmt: skip
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
