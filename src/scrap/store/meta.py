"""Kinds and tags: changes, their revisions, bulk edits."""

import json
import sqlite3
from typing import Any

from ..query import MEDIA, subtype_of
from .constants import (
    KIND_NAMES,
    KINDS,
    MAX_FIELDS,
    MAX_TAG,
    MAX_TAGS,
    META_REV,
    META_SOURCES,
    TODO,
    Value,
)
from .core import Core
from .db import transaction
from .errors import InvalidError
from .helpers import (
    check_todo,
    check_value,
    clean_tags,
    fields_for,
    meta_of,
    new_ulid,
    now,
    seconds_between,
)
from .todo import read as read_todo
from .todo import write as write_todo
from .types import FieldEdit, Meta

# Fields with a meaning of their own (a Later's link and summary): the pages' own edits
# set them, not edit_meta's free-form fields. status it does set, one of STATUSES, on a
# todo or a Later
RESERVED_FIELDS = frozenset({"personal", "source", "summary", "title", "body"})
STATUSES = ("open", "in_progress", "done", "cancelled")
MAX_FIELD_TEXT = 200  # characters, as the PWA's field has it (pages_api.FIELD)


def _fits_todo(name: str, value: Value | None) -> bool:
    """Whether page_todo can hold value as name (check_todo takes it)."""
    try:
        check_todo(name, value)
    except InvalidError:
        return False
    return True


class MetaMixin(Core):
    def _meta(self, conn: sqlite3.Connection, page_id: str) -> Meta:
        """A page's kind, whether it is fixed, and tags, as page_meta_rev has them."""
        row = conn.execute(
            "SELECT kind, kind_fixed FROM page WHERE id = ?", (page_id,)
        ).fetchone()
        tags = conn.execute("SELECT tag FROM tag WHERE page_id = ?", (page_id,))
        return Meta(row[0], row[1], sorted(r[0] for r in tags))

    def _defaults(
        self, conn: sqlite3.Connection, page_id: str, kind: str, fields: dict[str, Any]
    ) -> dict[str, Value]:
        """The fields a page gets on becoming kind: that kind's defaults it lacks."""
        url = conn.execute(
            "SELECT url FROM capture WHERE page_id = ? AND url IS NOT NULL"
            " ORDER BY received_at LIMIT 1",
            (page_id,),
        ).fetchone()
        defaults = fields_for(kind, url and url[0])
        room = max(0, MAX_FIELDS - len(fields))  # a full page gets fewer, or none
        missing = {k: v for k, v in defaults.items() if k not in fields}
        return dict(list(missing.items())[:room])

    def _record_meta(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        author: str,
        source: str,
        before: Meta,
        after: Meta,
        added: dict[str, Value] | None = None,
        reverts: int | None = None,
        batch: str | None = None,
        was: dict[str, Value] | None = None,
    ) -> int | None:
        """Record a change to a page's kind and tags (and the fields it set: the default
        fields a new kind added, or edit_meta's fields; was: their values before, or
        those it took off), returning its revision's id; none, no revision (a revert
        always is one). Coalesced: a change by the same author and source within
        self.window seconds of the page's latest revision being made folds into it
        (its after becomes this one's), as long as nothing else changed them between
        (that revision's after is this one's before); a fold that leaves it changing
        nothing drops it. A revert, or a change in a batch, never folds into another
        nor is folded into. Kinds that follow a page's text (task boxes file a note as
        a todo) and what ingest sets are not revisions: they are derived."""
        added, was = added or {}, was or {}
        if reverts is None and before == after and not added and not was:
            return None
        if source not in META_SOURCES:
            raise InvalidError(f"source must be one of {META_SOURCES}")
        stamp = now()
        last = conn.execute(
            f"{META_REV} WHERE page_id = ? ORDER BY id DESC LIMIT 1", (page_id,)
        ).fetchone()
        if (
            reverts is None
            and batch is None
            and last is not None
            and last["reverts"] is None
            and last["batch_id"] is None
            and (last["author"], last["source"]) == (author, source)
            and meta_of(last, "after") == before
            and 0 <= seconds_between(last["created_at"], stamp) < self.window
        ):
            prior = json.loads(last["fields_added"])
            # a field taken off now (in was, not added) is no longer one the burst set
            gone = {k for k in was if k not in added}
            merged = {k: v for k, v in {**prior, **added}.items() if k not in gone}
            first_was = json.loads(last["fields_was"])
            # the first's wins; and a field it added that was not there before has no
            # was: a later change must not make one up (a revert takes it off)
            fresh = {k: v for k, v in was.items() if k not in prior or k in first_was}
            merged_was = {**fresh, **first_was}
            if meta_of(last, "before") == after and not merged and not merged_was:
                # nothing, in all
                conn.execute("DELETE FROM page_meta_rev WHERE id = ?", (last["id"],))
                return None
            conn.execute(
                "UPDATE page_meta_rev SET kind_after = ?, fixed_after = ?,"
                " tags_after = ?, fields_added = ?, fields_was = ?, updated_at = ?"
                " WHERE id = ?",
                (after.kind, after.fixed, json.dumps(after.tags), json.dumps(merged),
                 json.dumps(merged_was), stamp, last["id"]),
            )  # fmt: skip
            return last["id"]
        cur = conn.execute(
            "INSERT INTO page_meta_rev (page_id, author, source, kind_before,"
            " kind_after, fixed_before, fixed_after, tags_before, tags_after,"
            " fields_added, fields_was, reverts, batch_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (page_id, author, source, before.kind, after.kind, before.fixed,
             after.fixed, json.dumps(before.tags), json.dumps(after.tags),
             json.dumps(added), json.dumps(was), reverts, batch, stamp, stamp),
        )  # fmt: skip
        return cur.lastrowid

    def _plan(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        before: Meta,
        after: Meta,
        edit: FieldEdit | None = None,
    ) -> tuple[
        dict[str, Any],
        dict[str, str | None],
        dict[str, Value],
        dict[str, Any],
        dict[str, Value],
    ]:
        """A page's fields once given after's kind (as the PWA's kind picker: that
        kind's defaults it lacks) and edit: its put set (None takes one off), and, for
        a revert, its drop and was undone: what the change it undoes set is taken off
        or changed back to what it was, unless changed since. A todo's own values
        (page_todo's due, priority, snoozed_until) are fields here, under their names.
        Returns the fields, those todo values (None: none), the fields added (set, or
        given back), those dropped (taken off or changed back: their values now) and
        the values the fields changed had before (was)."""
        edit = edit or FieldEdit()
        row = conn.execute("SELECT fields FROM page WHERE id = ?", (page_id,))
        stored = json.loads(row.fetchone()[0])
        added = {}
        if after.kind != before.kind:
            added = self._defaults(conn, page_id, after.kind, stored)
        # due, priority and snoozed_until are page_todo's; a stale page.fields key of
        # one's name (an import's, or an edit_meta's before #385) stays aside. Puts
        # act on page_todo only. A revert acts on page.fields instead to undo a value
        # page_todo does not hold (page_todo wins a tie), or to give one back to a
        # page a todo neither before nor after, or that page_todo cannot hold
        todo_now = read_todo(conn, page_id)
        in_json = {
            k
            for k in TODO
            if k in edit.drop.keys() | edit.was.keys()
            and not (
                (
                    todo_now[k] == edit.drop[k]
                    if k in edit.drop
                    else "todo" in (before.kind, after.kind)
                )
                and _fits_todo(k, edit.was.get(k))
            )
        }
        aside = {k: v for k, v in stored.items() if k in TODO and k not in in_json}
        own = {k: v for k, v in todo_now.items() if v is not None and k not in in_json}
        fields = {k: v for k, v in stored.items() if k not in aside}
        fields = {**fields, **added, **own}
        undone = {  # key -> what to give back (None: take it off)
            k: edit.was.get(k)
            for k in edit.drop.keys() | edit.was.keys()
            if fields.get(k) == edit.drop.get(k)
        }
        dropped = {k: fields[k] for k in undone if k in fields}
        gave = {k: v for k, v in undone.items() if v is not None}
        was: dict[str, Value] = dict(dropped)
        fields = {k: v for k, v in fields.items() if k not in undone} | gave
        for k, v in edit.put.items():
            if fields.get(k) == v:
                continue
            if k in fields:
                was[k] = fields[k]
            fields.pop(k, None)
            if v is not None:
                fields[k], added[k] = v, v
        added |= gave
        values = {k: fields.pop(k, None) for k in TODO if k not in in_json}
        fields |= aside
        if len(fields) > MAX_FIELDS:
            raise InvalidError(f"a page has at most {MAX_FIELDS} fields")
        return fields, values, added, dropped, was

    def _put_meta(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        before: Meta,
        after: Meta,
        author: str,
        source: str,
        reverts: int | None = None,
        batch: str | None = None,
        edit: FieldEdit | None = None,
    ) -> tuple[int | None, dict[str, Value], dict[str, Any], dict[str, Value]]:
        """Give a page after's kind (with its fields: _plan), fixed or not, and tags,
        as a revision; its search chunk again. Returns the revision's id, the fields
        added and removed, and the values of those changed before."""
        fields, values, added, dropped, was = self._plan(
            conn, page_id, before, after, edit
        )
        conn.execute(
            "UPDATE page SET kind = ?, kind_fixed = ?, fields = ? WHERE id = ?",
            (after.kind, after.fixed, json.dumps(fields), page_id),
        )
        if any(k in TODO for k in added.keys() | dropped.keys() | was.keys()):
            write_todo(conn, page_id, values)
        if after.tags != before.tags:
            conn.execute("DELETE FROM tag WHERE page_id = ?", (page_id,))
            conn.executemany(
                "INSERT INTO tag VALUES (?, ?)", [(page_id, t) for t in after.tags]
            )
            self._model_tags(conn, page_id, after.tags)  # as a PWA tag save
        if after.tags != before.tags or added or dropped or was:
            self.reindex(conn, page_id)  # (its summary is a field)
        revision = self._record_meta(
            conn, page_id, author, source, before, after, added, reverts, batch, was
        )
        return revision, added, dropped, was

    @staticmethod
    def _change(
        page: sqlite3.Row,
        before: Meta,
        after: Meta,
        revision: int | None,
        added: dict[str, Any],
        dropped: dict[str, Any] | None = None,
        was: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """What a metadata edit did (or, in a dry run, would do) to a page."""
        return {
            "id": page["id"], "slug": page["slug"], "title": page["title"],
            "changed": before != after or bool(added or dropped or was),
            "revision": revision,
            "kind_before": before.kind, "kind_after": after.kind,
            "fixed_before": bool(before.fixed), "fixed_after": bool(after.fixed),
            "tags_before": before.tags, "tags_after": after.tags,
            "tags_added": [t for t in after.tags if t not in before.tags],
            "tags_removed": [t for t in before.tags if t not in after.tags],
            "fields_added": added, "fields_removed": dropped or {},
            "fields_was": was or {},
        }  # fmt: skip

    def _apply(
        self,
        conn: sqlite3.Connection,
        page: sqlite3.Row,
        before: Meta,
        after: Meta,
        author: str,
        source: str,
        dry_run: bool,
        batch: str | None,
        reverts: int | None = None,
        edit: FieldEdit | None = None,
    ) -> dict[str, Any]:
        """One page's metadata change, or with dry_run what it would be."""
        if dry_run:
            _, _, added, dropped, was = self._plan(
                conn, page["id"], before, after, edit
            )
            return self._change(page, before, after, None, added, dropped, was)
        revision, added, dropped, was = self._put_meta(
            conn, page["id"], before, after, author, source, reverts, batch, edit
        )
        out = self._change(page, before, after, revision, added, dropped, was)
        return {**out, "batch": batch if revision else None}

    @staticmethod
    def _field_puts(fields: dict[str, Value | None] | None) -> dict[str, Any]:
        """The fields edit_meta is to set, checked: a name and value the PWA could
        show, a media_type one of the known media, no subtype of its own, and a todo's
        due and snoozed_until dates, its priority one of PRIORITIES."""
        put = dict(fields or {})
        for name, value in put.items():
            if not name or len(name) > MAX_TAG or name.startswith("_"):
                raise InvalidError(f"a field name must be 1 to {MAX_TAG} characters")
            if name in RESERVED_FIELDS:
                raise InvalidError(
                    f"field {name} has a meaning of its own: not set here"
                )
            if isinstance(value, str) and len(value) > MAX_FIELD_TEXT:
                raise InvalidError(f"field {name}: at most {MAX_FIELD_TEXT} characters")
            if name in TODO:
                check_todo(name, value)
            elif value is not None:
                check_value(name, value)
        if "status" in put and put["status"] not in STATUSES:
            raise InvalidError(f"status must be one of {STATUSES}")
        if "subtype" in put:
            raise InvalidError("subtype follows media_type: set media_type instead")
        if put.get("media_type") not in (None, *MEDIA):
            raise InvalidError(f"media_type must be one of {tuple(MEDIA)}")
        return put

    @staticmethod
    def _subtyped(put: dict[str, Any], kind: str) -> dict[str, Any]:
        """put, and for a Later with a media_type in it the subtype it gives (read
        for none)."""
        if "media_type" not in put or kind != "consume":
            return put
        return {**put, "subtype": subtype_of(put["media_type"])}

    def edit_meta(
        self,
        keys: list[str],
        author: str,
        source: str,
        kind: str | None = None,
        add: list[str] | None = None,
        remove: list[str] | None = None,
        tags: list[str] | None = None,
        dry_run: bool = False,
        batch: bool = False,
        fields: dict[str, Value | None] | None = None,
    ) -> dict[str, Any]:
        """Set the kind of these pages (ids or slugs; fixed, as the PWA's picker
        does, even if it is theirs already) and/or change their tags: add and remove
        these (exact tags: removing a leaves a/b), or replace them all with tags. Each
        page changed is a revision (see _record_meta); with batch (a query's pages,
        however many) or several distinct pages, all of them share a batch id,
        returned, which revert_batch undoes at once. updated_at stays as it was, as
        for the PWA's tag and kind edits. All or nothing: an unknown page or a
        refused change saves none. dry_run: say what would change, save nothing.
        fields sets (None takes off) these fields of every page, as part of the same
        revision (fields_added, and their values before: fields_was): a Later's
        media_type also sets its subtype, which it never has on its own; status (open,
        in_progress, done or cancelled) is a todo's or a Later's, as the PWA's tick;
        due, priority and snoozed_until are a todo's (checked as check_todo; kept in
        page_todo, not fields). Never the title or the text."""
        put = self._field_puts(fields)
        # a todo's own values (due, priority, snoozed_until): page_todo's, not fields
        todo_put = set(put) & set(TODO)
        kind = KIND_NAMES.get(kind, kind) if kind is not None else None
        if kind not in (None, *KINDS):
            raise InvalidError(f"kind must be one of {KINDS}")
        add, remove = clean_tags(add or []), clean_tags(remove or [])
        if tags is not None and (add or remove):
            raise InvalidError("give tags to replace them all, or tags to add/remove")
        if set(add) & set(remove):
            raise InvalidError("a tag cannot be both added and removed")
        tags = None if tags is None else clean_tags(tags)
        out: list[dict[str, Any]] = []
        with self.connect() as conn, transaction(conn):
            pages: dict[str, sqlite3.Row] = {}
            for key in keys:  # each page once, however named
                page = self._page_row(conn, key)
                pages.setdefault(page["id"], page)
            several = batch or len(pages) > 1
            batch_id = new_ulid() if several and not dry_run else None
            for page in pages.values():
                before = self._meta(conn, page["id"])
                new = tags if tags is not None else [
                    t for t in before.tags if t not in remove
                ] + add  # fmt: skip
                after = Meta(
                    kind or before.kind, 1 if kind else before.fixed, sorted(set(new))
                )
                if len(after.tags) > MAX_TAGS:
                    raise InvalidError(f"{page['slug']}: over {MAX_TAGS} tags")
                if "status" in put and before.kind not in ("todo", "consume"):
                    raise InvalidError(
                        f"{page['slug']}: status is a todo's or a Later's: make it "
                        "one first (in an earlier call)"
                    )
                if todo_put and before.kind != "todo":
                    raise InvalidError(
                        f"{page['slug']}: {', '.join(sorted(todo_put))}"
                        " is a todo's: make it one first (in an earlier call)"
                    )
                if put.get("media_type") and after.kind != "consume":
                    raise InvalidError(  # else a later kind change would pair it with
                        f"{page['slug']}: media_type is a Later's: make it one first"
                    )  # a subtype of read
                out.append(self._apply(
                    conn, page, before, after, author, source, dry_run, batch_id,
                    edit=FieldEdit(put=self._subtyped(put, after.kind)),
                ))  # fmt: skip
        changed = any(c["revision"] for c in out)
        return {"batch": batch_id if changed else None, "pages": out}

    def rename_tag(
        self,
        old: str,
        new: str,
        author: str,
        source: str,
        dry_run: bool = False,
        limit: int = 50,
        merge: bool = False,
    ) -> dict[str, Any]:
        """Rename a tag on every page with it (not the trash's), and the tags under it
        (old/x becomes new/x), as one batch (see edit_meta). Refused: more than limit
        pages, a new name under the old one, and, unless merge, a new name already in
        use (a merge cannot be undone by renaming back: only by reverting the batch).
        dry_run: say what would change, save nothing."""
        old, new = clean_tags([old])[0], clean_tags([new])[0]
        if old == new:
            raise InvalidError("the new name is the old one")
        if new.startswith(f"{old}/"):
            raise InvalidError(f"{new!r} is under {old!r}: it would nest again")

        def renamed(tag: str) -> str:
            if tag == old or tag.startswith(f"{old}/"):
                tag = new + tag[len(old) :]
            if len(tag) > MAX_TAG:
                raise InvalidError(f"a tag must be 1 to {MAX_TAG} characters: {tag!r}")
            return tag

        under = (
            "SELECT DISTINCT t.page_id FROM tag t JOIN page p ON p.id = t.page_id"
            " WHERE p.deleted_at IS NULL AND (t.tag = ? OR substr(t.tag, 1, ?) = ?)"
            " ORDER BY t.page_id"
        )
        batch_id = None if dry_run else new_ulid()
        out: list[dict[str, Any]] = []
        with self.connect() as conn, transaction(conn):
            ids = [r[0] for r in conn.execute(under, (old, len(old) + 1, f"{old}/"))]
            if len(ids) > limit:
                raise InvalidError(
                    f"{old!r} is on {len(ids)} pages, more than {limit}: raise limit"
                )
            in_use = (  # the trash's too: restoring a page would merge them unasked
                "SELECT 1 FROM tag WHERE tag = ? OR substr(tag, 1, ?) = ? LIMIT 1"
            )
            if (
                not merge
                and conn.execute(in_use, (new, len(new) + 1, f"{new}/")).fetchone()
            ):
                raise InvalidError(
                    f"{new!r} is in use (perhaps only in the trash): renaming into it"
                    " merges the two (merge)"
                )
            for page_id in ids:
                page = self._page_row(conn, page_id)
                before = self._meta(conn, page_id)
                after = before._replace(tags=sorted({renamed(t) for t in before.tags}))
                out.append(self._apply(
                    conn, page, before, after, author, source, dry_run, batch_id
                ))  # fmt: skip
        changed = any(c["revision"] for c in out)
        return {"batch": batch_id if changed else None, "pages": out}
