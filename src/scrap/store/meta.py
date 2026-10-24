"""Kinds and tags: changes, their revisions, bulk edits."""

import json
import sqlite3
from typing import Any

from .constants import (
    KIND_NAMES,
    KINDS,
    MAX_FIELDS,
    MAX_TAG,
    MAX_TAGS,
    MCP,
    META_REV,
    META_SOURCES,
    Value,
)
from .core import Core
from .db import transaction
from .errors import InvalidError
from .helpers import clean_tags, fields_for, meta_of, new_ulid, now, seconds_between
from .types import Meta


class MetaMixin(Core):
    def by_claude(self, conn: sqlite3.Connection, page_id: str) -> bool:
        """Whether a page was written over MCP (its first capture's source)."""
        row = conn.execute(
            "SELECT source FROM capture WHERE page_id = ?"
            " ORDER BY received_at, id LIMIT 1",
            (page_id,),
        ).fetchone()
        return bool(row) and row[0] == MCP

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
    ) -> int | None:
        """Record a change to a page's kind and tags (and the default fields a new
        kind added), returning its revision's id; none, no revision (a revert always
        is one). Coalesced: a change by the same author and source within
        self.window seconds of the page's latest revision being made folds into it
        (its after becomes this one's), as long as nothing else changed them between
        (that revision's after is this one's before); a fold that leaves it changing
        nothing drops it. A revert, or a change in a batch, never folds into another
        nor is folded into. Kinds that follow a page's text (task boxes file a note as
        a todo) and what ingest sets are not revisions: they are derived."""
        added = added or {}
        if reverts is None and before == after and not added:
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
            merged = {**json.loads(last["fields_added"]), **added}
            if meta_of(last, "before") == after and not merged:  # nothing, in all
                conn.execute("DELETE FROM page_meta_rev WHERE id = ?", (last["id"],))
                return None
            conn.execute(
                "UPDATE page_meta_rev SET kind_after = ?, fixed_after = ?,"
                " tags_after = ?, fields_added = ?, updated_at = ? WHERE id = ?",
                (after.kind, after.fixed, json.dumps(after.tags), json.dumps(merged),
                 stamp, last["id"]),
            )  # fmt: skip
            return last["id"]
        cur = conn.execute(
            "INSERT INTO page_meta_rev (page_id, author, source, kind_before,"
            " kind_after, fixed_before, fixed_after, tags_before, tags_after,"
            " fields_added, reverts, batch_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (page_id, author, source, before.kind, after.kind, before.fixed,
             after.fixed, json.dumps(before.tags), json.dumps(after.tags),
             json.dumps(added), reverts, batch, stamp, stamp),
        )  # fmt: skip
        return cur.lastrowid

    def _plan(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        before: Meta,
        after: Meta,
        drop: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Value], dict[str, Any]]:
        """A page's fields once given after's kind: with the defaults a new kind adds
        (as the PWA's kind picker), and without those of drop that still hold the
        value it gives (a revert takes off what the change it undoes added, unless
        changed since). Returns the fields, those added and those removed."""
        row = conn.execute("SELECT fields FROM page WHERE id = ?", (page_id,))
        fields = json.loads(row.fetchone()[0])
        added = {}
        if after.kind != before.kind:
            added = self._defaults(conn, page_id, after.kind, fields)
        dropped = {
            k: v for k, v in (drop or {}).items() if fields.get(k) == v
        }  # fmt: skip
        fields = {k: v for k, v in {**fields, **added}.items() if k not in dropped}
        if len(fields) > MAX_FIELDS:
            raise InvalidError(f"a page has at most {MAX_FIELDS} fields")
        return fields, added, dropped

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
        drop: dict[str, Any] | None = None,
    ) -> tuple[int | None, dict[str, Value], dict[str, Any]]:
        """Give a page after's kind (with its fields: _plan), fixed or not, and tags,
        as a revision; its search chunk again. Returns the revision's id and the
        fields added and removed."""
        fields, added, dropped = self._plan(conn, page_id, before, after, drop)
        conn.execute(
            "UPDATE page SET kind = ?, kind_fixed = ?, fields = ? WHERE id = ?",
            (after.kind, after.fixed, json.dumps(fields), page_id),
        )
        if after.tags != before.tags:
            conn.execute("DELETE FROM tag WHERE page_id = ?", (page_id,))
            conn.executemany(
                "INSERT INTO tag VALUES (?, ?)", [(page_id, t) for t in after.tags]
            )
            self._model_tags(conn, page_id, after.tags)  # as a PWA tag save
            self.reindex(conn, page_id)
        revision = self._record_meta(
            conn, page_id, author, source, before, after, added, reverts, batch
        )
        return revision, added, dropped

    @staticmethod
    def _change(
        page: sqlite3.Row,
        before: Meta,
        after: Meta,
        revision: int | None,
        added: dict[str, Any],
        dropped: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """What a metadata edit did (or, in a dry run, would do) to a page."""
        return {
            "id": page["id"], "slug": page["slug"], "title": page["title"],
            "changed": before != after or bool(added or dropped),
            "revision": revision,
            "kind_before": before.kind, "kind_after": after.kind,
            "fixed_before": bool(before.fixed), "fixed_after": bool(after.fixed),
            "tags_before": before.tags, "tags_after": after.tags,
            "tags_added": [t for t in after.tags if t not in before.tags],
            "tags_removed": [t for t in before.tags if t not in after.tags],
            "fields_added": added, "fields_removed": dropped or {},
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
        drop: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """One page's metadata change, or with dry_run what it would be."""
        if dry_run:
            _, added, dropped = self._plan(conn, page["id"], before, after, drop)
            return self._change(page, before, after, None, added, dropped)
        revision, added, dropped = self._put_meta(
            conn, page["id"], before, after, author, source, reverts, batch, drop
        )
        out = self._change(page, before, after, revision, added, dropped)
        return {**out, "batch": batch if revision else None}

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
    ) -> dict[str, Any]:
        """Set the kind of these pages (ids or slugs; fixed, as the PWA's picker
        does, even if it is theirs already) and/or change their tags: add and remove
        these (exact tags: removing a leaves a/b), or replace them all with tags. Each
        page changed is a revision (see _record_meta); with batch (a query's pages,
        however many) or several distinct pages, all of them share a batch id,
        returned, which revert_batch undoes at once. updated_at stays as it was, as
        for the PWA's tag and kind edits. All or nothing: an unknown page or a
        refused change saves none. dry_run: say what would change, save nothing.
        Never the title, the text or other fields."""
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
                out.append(self._apply(
                    conn, page, before, after, author, source, dry_run, batch_id
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
