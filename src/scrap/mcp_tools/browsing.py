"""The tools that list pages: recent, trash, todos and tags."""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..store import KIND_NAMES
from .context import Ctx, text
from .limits import Limit


def register_browsing(mcp: MCPServer, ctx: Ctx) -> None:
    """recent, trash, todos and tags."""
    store = ctx.store
    link = ctx.link
    rows = ctx.rows
    checked = ctx.checked

    @mcp.tool()
    def recent(
        limit: Limit = 20,
        kind: Annotated[str | None, Field(description="note, todo, read, ...")] = None,
    ) -> dict[str, Any]:
        """The most recently changed pages, newest first; only one kind if given.
        Rows as search's (image_count and the first image's fields), no snippet;
        for recent photos, search has:image."""
        kind = KIND_NAMES.get(kind, kind) if kind else None
        return {"results": rows(checked(store.recent, limit, kind))}

    @mcp.tool()
    def trash(limit: Annotated[int, Field(ge=1, le=100)] = 20) -> dict[str, Any]:
        """The pages the user deleted, which are in the trash, most recently deleted
        first: {id, slug, url, title, kind, deleted_at, updated_at}. Every other tool
        treats them as absent; read and revisions show one read only, and undelete
        brings it back."""
        found = store.trash(limit)
        return {"results": [{**t, "url": link(t["slug"])} for t in found]}

    @mcp.tool()
    def todos(
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
        sort: Annotated[
            str | None,
            Field(description="due (soonest first) or priority (high first)"),
        ] = None,
    ) -> dict[str, Any]:
        """Todos not done or cancelled (open or in progress) and not snoozed, newest
        first, or by due date or priority (those with none last). Each has its due
        date (YYYY-MM-DD) and priority (high, medium, low), or None. For overdue ones,
        search "kind:todo due:<today -is:done -is:cancelled"; for those snoozed (hidden
        until their snoozed_until day), "kind:todo is:snoozed"."""
        if sort not in (None, "due", "priority"):
            raise ToolError("sort must be due or priority")
        order = f" sort:{sort}" if sort else ""
        query = f"kind:todo -is:done -is:cancelled -is:snoozed{order}"
        hits = store.search(query, limit)
        return {"results": rows(hits)}

    @mcp.tool()
    def tags(
        prefix: str = "", limit: Annotated[int, Field(ge=1, le=2000)] = 300
    ) -> dict[str, Any]:
        """Tags in use with how many pages have each, most used first (a counts
        a/b's pages too); only those starting with prefix, if given. Reuse these
        when writing rather than inventing new ones."""
        prefix = text(prefix, "prefix").lower()
        found = [t[:2] for t in store.tags() if t[0].startswith(prefix)]
        found.sort(key=lambda t: (-t[1], t[0]))
        return {"tags": found[:limit], "total": len(found)}
