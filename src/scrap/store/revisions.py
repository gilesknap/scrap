"""Revisions of a page: history, reverts, text edits."""

import json
import sqlite3
from collections.abc import Callable
from typing import Any

from ..markdown import tasks
from . import roles
from .constants import MCP, META_REV, PAGE_KINDS, REV_INSERT
from .core import Core
from .db import _rows, transaction
from .errors import ConflictError, InvalidError, NoSuchRevision, NotFoundError
from .helpers import (
    body_refs,
    boxes_before,
    check_page,
    lines,
    meta_of,
    meta_row,
    new_ulid,
    now,
    seconds_between,
)
from .indexing import debounce, enrich_on, queue_enrich
from .roles import may_rekind, should_enrich
from .trash_revs import trash_revs
from .types import FieldEdit


class RevisionsMixin(Core):
    def revert_meta(
        self, revision: int, author: str, source: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """Undo a metadata revision: give its page back the kind (fixed or not) and
        tags it had just before it, so undoing later ones too, and take off the
        default fields its kind change added (those not changed since). The revert is
        a revision of its own, never folded into another, so it can be undone in
        turn: nothing is lost. No revision (None) if the page has them already.
        dry_run: save nothing."""
        with self.connect() as conn, transaction(conn):
            row = conn.execute(f"{META_REV} WHERE id = ?", (revision,)).fetchone()
            if row is None:
                raise NoSuchRevision(f"revision {revision}")
            page = self._page_row(conn, row["page_id"])  # not in the trash
            out = self._revert(conn, page, row, author, source, dry_run, None)
            return {**out, "reverts": revision}

    def _revert(
        self,
        conn: sqlite3.Connection,
        page: sqlite3.Row,
        row: sqlite3.Row,
        author: str,
        source: str,
        dry_run: bool,
        batch: str | None,
    ) -> dict[str, Any]:
        before, after = self._meta(conn, page["id"]), meta_of(row, "before")
        undo = FieldEdit(
            drop=json.loads(row["fields_added"]), was=json.loads(row["fields_was"])
        )
        _, _, added, dropped, was = self._plan(conn, page["id"], before, after, undo)
        if dry_run or (before == after and not added and not dropped):
            return self._change(page, before, after, None, added, dropped, was)
        return self._apply(
            conn, page, before, after, author, source, False, batch, row["id"], undo
        )

    def revert_batch(
        self, batch: str, author: str, source: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """Undo every revision of a batch (an edit_meta or rename_tag of several
        pages, or a batch revert) at once: as revert_meta, page by page, as a new
        batch, itself undoable at once. Refused, saving nothing, if any page's kind
        or tags changed since (conflicts; revert those pages' revisions one by one);
        pages in the trash are skipped. dry_run: say what would change, and which
        pages conflict, and save nothing."""
        with self.connect() as conn, transaction(conn):
            rows = conn.execute(
                f"{META_REV} WHERE batch_id = ? ORDER BY id", (batch,)
            ).fetchall()
            if not rows:
                raise NoSuchRevision(f"batch {batch}")
            pages, skipped, conflicts = [], [], []
            for row in rows:
                try:
                    page = self._page_row(conn, row["page_id"])
                except NotFoundError:
                    skipped.append({"id": row["page_id"], "revision": row["id"]})
                    continue
                if self._meta(conn, page["id"]) != meta_of(row, "after"):
                    conflicts.append({
                        "id": page["id"], "slug": page["slug"], "revision": row["id"],
                    })  # fmt: skip
                pages.append((page, row))
            if conflicts and not dry_run:
                slugs = ", ".join(c["slug"] for c in conflicts)
                raise InvalidError(
                    f"changed since batch {batch}, so nothing was reverted: {slugs}"
                    " (revert those pages' revisions one by one)"
                )
            new = None if dry_run else new_ulid()
            out = [
                {**self._revert(conn, p, r, author, source, dry_run, new),
                 "reverts": r["id"]}
                for p, r in pages
            ]  # fmt: skip
        changed = any(c.get("revision") for c in out)
        return {
            "batch": new if changed else None, "reverts_batch": batch, "pages": out,
            "skipped": skipped, "conflicts": conflicts,
        }  # fmt: skip

    def revisions(
        self,
        key: str | None = None,
        limit: int = 20,
        batch: str | None = None,
        trashed: bool = False,
    ) -> dict[str, Any]:
        """A page's history, newest first: its metadata revisions (kind, fixed or
        not, and tags, before and after, each with who made it, when, and its batch)
        and its text revisions (page_rev: rev, title, author, when and size, not the
        text). With batch, only that batch's revisions, of every page (with key, of
        that page). With neither, the recent changes of every page not in the trash:
        the latest metadata revisions and the latest text revisions (each with its
        page's id and slug), newest first. trash: the moves into and out of the trash
        (trash_revs) of that page, that batch, or (with neither) every page, newest
        first, at most limit. With trashed, key may be a page in the trash (then
        deleted_at is returned)."""
        with self.connect() as conn:
            page = self._page_row(conn, key, trashed) if key else None
            feed = page is None and batch is None
            where, args = [], []
            if feed:
                where.append(
                    "page_id IN (SELECT id FROM page WHERE deleted_at IS NULL)"
                )
            if page is not None:
                where.append("page_id = ?")
                args.append(page["id"])
            if batch is not None:
                where.append("batch_id = ?")
                args.append(batch)
            meta = conn.execute(
                f"{META_REV} WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
                (*args, limit + 1),
            ).fetchall()
            more, meta = len(meta) > limit, meta[:limit]
            slugs = dict(conn.execute(
                "SELECT id, slug FROM page"
                " WHERE id IN (SELECT value FROM json_each(?))",
                (json.dumps([r["page_id"] for r in meta]),),
            ).fetchall())  # fmt: skip
            text = _rows(
                conn,
                "SELECT rev, title, author, source, created_at,"
                " length(CAST(body AS BLOB))"
                " AS bytes FROM page_rev WHERE page_id = ? ORDER BY rev DESC LIMIT ?",
                page["id"], limit,
            ) if page is not None else _rows(
                conn,
                "SELECT r.page_id, p.slug, r.rev, r.title, r.author, r.source,"
                " r.created_at,"
                " length(CAST(r.body AS BLOB)) AS bytes FROM page_rev r"
                " JOIN page p ON p.id = r.page_id WHERE p.deleted_at IS NULL"
                " ORDER BY r.created_at DESC, r.page_id DESC, r.rev DESC LIMIT ?",
                limit,
            ) if feed else []  # fmt: skip
            trash = trash_revs(conn, None if page is None else page["id"], batch, limit)
        out: dict[str, Any] = {
            "meta": [{**meta_row(r), "slug": slugs.get(r["page_id"])} for r in meta],
            "more": more,  # older revisions than limit allows
            "text": text,
            "trash": trash,
        }
        if page is not None:
            out |= {
                "id": page["id"], "slug": page["slug"], "title": page["title"],
                "kind": page["kind"], "rev": page["rev"],
                "deleted_at": page["deleted_at"],
            }  # fmt: skip
        return out

    def text_revision(
        self, key: str, rev: int, trashed: bool = False
    ) -> dict[str, Any]:
        """One text revision of a page: its title and body then, who wrote it (author,
        and source: mcp for Claude's, else web), when."""
        with self.connect() as conn:
            page = self._page_row(conn, key, trashed)
            row = conn.execute(
                "SELECT rev, title, body, author, source, created_at FROM page_rev"
                " WHERE page_id = ? AND rev = ?",
                (page["id"], rev),
            ).fetchone()
        if row is None:
            raise NoSuchRevision(f"revision {rev} of {key}")
        return dict(row)

    def edit_text(
        self,
        key: str,
        author: str,
        change: Callable[[sqlite3.Connection, sqlite3.Row], tuple[str, str]],
        base_rev: int | None = None,
        dry_run: bool = False,
        fold: bool = True,
        *,
        source: str,
    ) -> dict[str, Any]:
        """Change the title and/or body of a page (not one in the trash) as a new
        text revision by author from source (mcp: Claude's; see REV_INSERT):
        change(conn, page) gives its new title and body
        from the current ones (raising InvalidError to refuse). Refused
        (ConflictError) if base_rev is given and is not the page's current rev.
        Nothing is written if they are what the page has, nor with dry_run. Returns
        the page's id, slug, rev_before and rev (the new one, or rev_before), the
        title and body before and after, changed, and folded (the revision a burst
        folded into this one, else None). With fold, see _put_text."""
        with self.connect() as conn, transaction(conn):
            page = self._page_row(conn, key)
            if base_rev is not None and base_rev != page["rev"]:
                raise ConflictError(page["rev"])
            title, body = change(conn, page)
            if not title.strip():
                raise InvalidError("title must not be empty")
            body = check_page(lines(body), page["body"])
            changed = (title, body) != (page["title"], page["body"])
            rev, folded = page["rev"], None
            if changed and not dry_run:
                rev, folded = self._put_text(
                    conn, page, title, body, author, source, fold
                )
            return {
                "id": page["id"], "slug": page["slug"], "rev_before": page["rev"],
                "rev": rev, "changed": changed, "folded": folded,
                "title_before": page["title"], "title": title,
                "body_before": page["body"], "body": body,
            }  # fmt: skip

    def _put_text(
        self,
        conn: sqlite3.Connection,
        page: sqlite3.Row,
        title: str,
        body: str,
        author: str,
        source: str,
        fold: bool,
    ) -> tuple[int, int | None]:
        """Write a page's new title and body as text revision rev + 1, returning it
        and the revision folded into it (else None).

        Coalescing (fold): if the page's latest text revision is by the same author
        from the same source, is not its first, was made within self.window seconds,
        and does not hold the body of an earlier revision (a revert's, which is never
        folded into, whatever its title), and whose files this text still refers to
        all of (an embed deleted in the burst keeps the revision that had it, so the
        file counts as removed, GONE, not as never placed: #490), the burst's text
        replaces it: that revision
        goes and this one keeps its created_at. The number still moves on (rev + 1,
        never a number used before),
        since rev is the PWA's edit token: an editor holding the folded revision
        gets a conflict (409), never a silent overwrite. A burst leaves a gap in the
        numbers."""
        stamp = now()
        created, folded = stamp, None
        last = conn.execute(
            "SELECT rev, author, source, body, created_at FROM page_rev"
            " WHERE page_id = ? AND rev = ?",
            (page["id"], page["rev"]),
        ).fetchone()
        if (
            fold
            and last is not None
            and last["rev"] > 1
            and (last["author"], last["source"]) == (author, source)
            and 0 <= seconds_between(last["created_at"], stamp) < self.window
            and body_refs(last["body"]) <= body_refs(body)
            and not conn.execute(
                "SELECT 1 FROM page_rev r JOIN page_rev l"
                " ON l.page_id = r.page_id AND l.rev = ?"
                " WHERE r.page_id = ? AND r.rev < l.rev"
                " AND r.body = l.body LIMIT 1",
                (last["rev"], page["id"]),
            ).fetchone()
        ):
            conn.execute(
                "DELETE FROM page_rev WHERE page_id = ? AND rev = ?",
                (page["id"], last["rev"]),
            )
            created, folded = last["created_at"], last["rev"]
        rev = page["rev"] + 1
        conn.execute(
            "UPDATE page SET title = ?, body = ?, updated_at = ? WHERE id = ?",
            (title, body, stamp, page["id"]),
        )
        conn.execute(
            REV_INSERT, (page["id"], rev, title, body, author, source, created)
        )
        self._body(conn, page["id"], boxes_before(page))
        if source == MCP:  # Claude's
            self._unbox(conn, page)
        self.reindex(conn, page["id"])
        if enrich_on() and should_enrich(conn, page["id"]):  # as for the PWA's saves
            queue_enrich(conn, page["id"], "save", debounce())
        return rev, folded

    def _unbox(self, conn: sqlite3.Connection, page: sqlite3.Row) -> None:
        """Claude's text revision (a text revert) took away the boxes of a todo that
        its own boxes made (ADR 26): an unfixed todo, still with its default status,
        whose previous text had boxes and no revision by anyone but Claude ever had
        (so the boxes are Claude's, even if a fold deleted the revision that added
        them). It goes back to what it was filed as before: for a photo page, the kind
        photo ingest chose, else a note. A todo the user filed or touched stays."""
        now_ = conn.execute(
            "SELECT body, kind, kind_fixed, fields FROM page WHERE id = ?",
            (page["id"],),
        ).fetchone()
        if (
            not may_rekind(now_["kind"], now_["kind_fixed"], ("todo",))
            or tasks(now_["body"])[1]
            or not tasks(page["body"])[1]
            or json.loads(now_["fields"]).get("status", "open") != "open"
        ):  # the cheap exits first: the scan below reads every revision by others
            return
        theirs = conn.execute(
            "SELECT body FROM page_rev WHERE page_id = ? AND source <> ?",
            (page["id"], MCP),
        )
        if any(tasks(r[0])[1] for r in theirs):  # stops at the first with boxes
            return
        seen = conn.execute(
            "SELECT json_extract(d.data, '$.kind') FROM derived d JOIN capture c"
            " ON c.id = d.capture_id WHERE c.page_id = ? AND d.kind = 'description'"
            " AND d.superseded_at IS NULL ORDER BY d.id LIMIT 1",
            (page["id"],),
        ).fetchone()
        kind = PAGE_KINDS.get(seen[0], "note") if seen else "note"
        conn.execute("UPDATE page SET kind = ? WHERE id = ?", (kind, page["id"]))

    def edited_by_claude(self, page_id: str) -> bool:
        """Whether a page has a later text revision by Claude: MCP edits, or task
        boxes Claude added (roles.edited_by_claude, is:claude-edited)."""
        with self.connect() as conn:
            return roles.edited_by_claude(conn, page_id)

    def text_at(self, conn: sqlite3.Connection, page_id: str, rev: int) -> sqlite3.Row:
        """A page's text revision rev (title, body), or NotFoundError."""
        row = conn.execute(
            "SELECT rev, title, body FROM page_rev WHERE page_id = ? AND rev = ?",
            (page_id, rev),
        ).fetchone()
        if row is None:
            raise NoSuchRevision(f"revision {rev} of {page_id}")
        return row
