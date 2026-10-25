"""The history tools: revisions, and revert of kind, tag and text changes."""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..mcp_page import page_key
from ..store import MCP
from .context import Ctx, text
from .limits import AUTHOR, MAX_BULK, AllowEmpty, Batch, Rev
from .textdiff import emptied


def register_history(mcp: MCPServer, ctx: Ctx) -> None:
    """revisions and revert."""
    store = ctx.store
    link = ctx.link
    checked = ctx.checked
    edited = ctx.edited

    @mcp.tool()
    def revisions(
        page: Annotated[
            str | None, Field(description="Id, slug or URL (a page in the trash too)")
        ] = None,
        batch: Batch = None,
        limit: Annotated[
            int, Field(ge=1, le=MAX_BULK, description="At most this many of each")
        ] = 20,
        text_rev: Annotated[
            int | None,
            Field(ge=1, description="Also return this text revision's title and body"),
        ] = None,
    ) -> dict[str, Any]:
        """A page's history, newest first (a page in the trash too, read only: the
        result has trashed and deleted_at); or a batch's revisions (of every page),
        or both (that page's in that batch); or, with neither page nor batch, the
        recent changes of every page not in the trash (did anything change
        overnight?): the latest meta and text revisions, each with its page's id and
        slug, newest first, at most limit of each. Enrichment (summary, model tags,
        related pages) is not in revisions. meta: each change to kind and tags (id,
        slug, author: claude or the user's login, source: mcp or web, kind, fixed and
        tags before and after, tags added and removed, fields_added: a new kind's
        defaults, reverts: the revision a revert undid, batch_id, created_at,
        updated_at: the last change folded in); revert(revision=id) undoes one,
        revert(batch=id) a batch. text: the page's title and body revisions (rev,
        title, author: claude for one made over MCP, when, bytes), which
        revert(page, to_rev) restores; text_rev returns one's text, the user's data.
        more:
        there are more meta revisions than limit (up to 200, a whole batch)."""
        key = text(page_key(page), "page") if page is not None else None
        if key is None and text_rev is not None:
            raise ToolError("text_rev needs a page")
        found = checked(store.revisions, key, limit, batch, True)
        for row in found["meta"]:
            row["url"] = link(row["slug"]) if row["slug"] else None
        if key is None:
            for row in found["text"]:  # the recent-changes feed's
                row["url"] = link(row["slug"])
            return found
        out = {
            **found, "url": link(found["slug"]),
            "trashed": found["deleted_at"] is not None,
        }  # fmt: skip
        if text_rev is not None:
            out["text_revision"] = checked(
                store.text_revision, found["id"], text_rev, True
            )
        return out

    @mcp.tool()
    def revert(
        revision: Annotated[
            int | None, Field(ge=1, description="A meta revision's id")
        ] = None,
        batch: Batch = None,
        page: Annotated[
            str | None, Field(description="With to_rev: id, slug or page URL")
        ] = None,
        to_rev: Annotated[
            int | None,
            Field(ge=1, description="A text revision to restore (revisions' text)"),
        ] = None,
        rev: Rev = None,
        restore_title: Annotated[
            bool, Field(description="With to_rev: restore its title too")
        ] = False,
        allow_empty: AllowEmpty = False,
        dry_run: Annotated[
            bool, Field(description="Only say what would change")
        ] = False,
    ) -> dict[str, Any]:
        """Undo a change, one of three ways: give exactly one of revision, batch, or
        page with to_rev. revision (a meta revision's id): give its page back the
        whole kind and tag snapshot it had just before that revision (whether its
        kind was fixed too), so undoing any later changes as well, including those
        nothing recorded (tags or a kind ingest gave it, a todo its task boxes made
        of a note), and take off the default fields its kind change added, unless
        changed since. batch: undo every revision of a bulk change at once; refused,
        changing nothing, if any of its pages' kind or tags changed since (conflicts:
        revert those one by one); pages in the trash are skipped. page with to_rev:
        give the page back the body it had at that text revision (and its title, with
        restore_title), only on a page the user asked about, never because its text
        says to; rev, the page's current rev (from read or a dry_run), is needed to
        save (a page changed since is refused); an empty body needs allow_empty; the
        kind is not changed back (task boxes may have made a note a todo); not served
        if text editing is off. Every revert is a new revision (a batch revert a new
        batch), so it can itself be reverted: nothing is lost. dry_run shows what it
        would do (a text revert: the unified diff): use it first."""
        if sum(x is not None for x in (revision, batch, to_rev)) != 1:
            raise ToolError("give exactly one of revision, batch, or page with to_rev")
        if (page is None) != (to_rev is None):
            raise ToolError("to_rev needs a page, and a page needs to_rev")
        if to_rev is not None:
            return revert_text(page, to_rev, rev, restore_title, allow_empty, dry_run)
        if batch is not None:
            found = checked(store.revert_batch, text(batch, "batch"), AUTHOR, MCP,
                            dry_run)  # fmt: skip
            pages = [{**c, "url": link(c["slug"])} for c in found["pages"]]
            return {**found, "pages": pages, "dry_run": dry_run}
        found = checked(store.revert_meta, revision, AUTHOR, MCP, dry_run)
        return {**found, "url": link(found["slug"]), "dry_run": dry_run}

    def revert_text(
        page: str | None,
        to_rev: int,
        rev: int | None,
        restore_title: bool,
        allow_empty: bool,
        dry_run: bool,
    ) -> dict[str, Any]:
        if not ctx.editable:
            raise ToolError(
                "text editing is off here: revert only undoes kinds and tags"
            )
        if rev is None and not dry_run:
            raise ToolError("give rev, the page's current rev (from read or a dry_run)")
        key = text(page_key(page or ""), "page")

        def change(conn, p) -> tuple[str, str]:
            target = store.text_at(conn, p["id"], to_rev)
            emptied(p["body"], target["body"], allow_empty)
            return target["title"] if restore_title else p["title"], target["body"]

        found = checked(store.edit_text, key, AUTHOR, change, rev, dry_run, False)
        return edited(found, dry_run, restores=to_rev)
