"""The tools that change kinds and tags: edit_meta and rename_tag."""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..store import KINDS, MCP
from .context import Ctx, text
from .limits import (
    AUTHOR,
    MAX_BULK,
    MAX_TAGS,
    WRITE_KINDS,
    BulkLimit,
    DryRun,
)


def register_meta(mcp: MCPServer, ctx: Ctx) -> None:
    """edit_meta and rename_tag."""
    store = ctx.store
    checked = ctx.checked
    changes = ctx.changes
    tag_list = ctx.tag_list

    @mcp.tool()
    def edit_meta(
        pages: Annotated[
            list[str], Field(max_length=MAX_BULK, description="Ids or slugs")
        ] = [],  # noqa: B006
        query: Annotated[
            str | None,
            Field(description="Instead of pages: every page this search finds"),
        ] = None,
        kind: Annotated[
            str | None,
            Field(description="note, todo, read, board (whiteboard) or doc (document)"),
        ] = None,
        add_tags: Annotated[list[str], Field(max_length=MAX_TAGS)] = [],  # noqa: B006
        remove_tags: Annotated[list[str], Field(max_length=MAX_TAGS)] = [],  # noqa: B006
        set_tags: Annotated[
            list[str] | None,
            Field(max_length=MAX_TAGS, description="Replace all of its tags"),
        ] = None,
        dry_run: DryRun = False,
        limit: BulkLimit = 50,
    ) -> dict[str, Any]:
        """Change the kind and/or tags of pages, any page, the user's own too: the
        pages named, or every page a search query finds (refused if it finds more than
        limit). A kind given is fixed (ingest and task boxes no longer change it), as
        when the user picks one, and adds that kind's default fields it lacks. Tags:
        add_tags and remove_tags (exact: removing a leaves a/b), or set_tags to
        replace them all. Nothing else changes: not the title, the text or when it
        was last updated. Each page changed is a revision that revert undoes; quick
        changes to one named page fold into one. A query or several pages is a batch:
        its revisions share the returned batch id, and revert(batch=...) undoes them
        all at once. All or nothing. Try dry_run first for a bulk change."""
        if pages and query is not None:
            raise ToolError("give pages or a query, not both")
        if not pages and query is None:
            raise ToolError("give pages or a query")
        if kind is None and not (add_tags or remove_tags) and set_tags is None:
            raise ToolError("nothing to change: give a kind or tags")
        if kind is not None and kind not in WRITE_KINDS and kind not in KINDS:
            raise ToolError(f"kind must be one of {WRITE_KINDS} (board is whiteboard)")
        if query is not None:
            hits = checked(store.search, text(query, "query"), limit + 1)
            if len(hits) > limit:
                raise ToolError(
                    f"the query finds more than {limit} pages: narrow it, or raise "
                    f"limit (at most {MAX_BULK})"
                )
            keys = [h["id"] for h in hits]
        else:
            keys = [text(p, "page") for p in pages]
        found = checked(
            store.edit_meta, keys, AUTHOR, MCP, kind,
            tag_list(add_tags, "a tag"), tag_list(remove_tags, "a tag"),
            None if set_tags is None else tag_list(set_tags, "a tag"), dry_run,
            batch=query is not None,  # else several distinct pages: Store decides
        )  # fmt: skip
        return changes(found, dry_run)

    @mcp.tool()
    def rename_tag(
        old: Annotated[str, Field(max_length=200)],
        new: Annotated[str, Field(max_length=200)],
        merge: Annotated[
            bool,
            Field(description="Allow renaming into a tag in use, merging the two"),
        ] = False,
        dry_run: DryRun = False,
        limit: BulkLimit = 50,
    ) -> dict[str, Any]:
        """Rename a tag on every page that has it, and the tags under it (old/x
        becomes new/x), as one batch (revert(batch=...) undoes it). Refused: more than
        limit pages, a new name under the old one (a to a/b), and a new name already
        in use unless merge (renaming back cannot separate merged tags: only reverting
        the batch can). Returns each page's tags before and after."""
        found = checked(
            store.rename_tag, text(old, "old"), text(new, "new"), AUTHOR, MCP,
            dry_run, limit, merge,
        )  # fmt: skip
        return changes(found, dry_run)
