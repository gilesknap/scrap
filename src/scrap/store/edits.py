"""Changing a page: its text, kind, fields, tags and a todo's dates."""

import json
import sqlite3
from typing import Any

from ..markdown import tasks
from .constants import KINDS, MAX_FIELDS, MAX_TAGS, TODO, Value
from .core import Core
from .db import transaction
from .errors import ConflictError, InvalidError
from .helpers import (
    boxes_before,
    check_page,
    check_todo,
    check_value,
    clean_tags,
    fields_for,
    lines,
    now,
)
from .indexing import debounce, enrich_on, queue_enrich, should_enrich


class EditsMixin(Core):
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
