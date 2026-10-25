"""The tools that list: the trash and tags."""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .context import Ctx, text


def register_browsing(mcp: MCPServer, ctx: Ctx) -> None:
    """trash and tags."""
    store = ctx.store
    link = ctx.link

    @mcp.tool()
    def trash(limit: Annotated[int, Field(ge=1, le=100)] = 20) -> dict[str, Any]:
        """The pages the user deleted, which are in the trash, most recently deleted
        first: {id, slug, url, title, kind, deleted_at, updated_at}. Every other tool
        treats them as absent; read and revisions show one read only, and undelete
        brings it back."""
        found = store.trash(limit)
        return {"results": [{**t, "url": link(t["slug"])} for t in found]}

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
