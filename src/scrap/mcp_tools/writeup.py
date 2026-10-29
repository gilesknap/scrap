"""The writeup tool: ask for a write-up of a page's image (#453)."""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from .. import enrich
from ..mcp_page import page_key
from ..store import enrich_on
from .context import Ctx, text
from .limits import AUTHOR


def register_writeup(mcp: MCPServer, ctx: Ctx) -> None:
    """writeup."""
    store = ctx.store
    checked = ctx.checked

    @mcp.tool()
    def writeup(
        page: Annotated[str, Field(description="Id, slug or page URL")],
        guidance: Annotated[
            str | None,
            Field(
                max_length=enrich.MAX_GUIDANCE,
                description="What to focus on or what words mean, kept for the next "
                "write-up too (empty: none); omit to leave the page's as it is",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Ask scrap's Claude to write up the image of a page (a screenshot of a
        readout, a document, a whiteboard) now, or again: one model call from the
        shared daily budget, so only for a page the user asked about. Queued, not
        waited for: read the page later and its write-up is by_model.writeup (its
        values with units, status and the capture date, or a board's explanation);
        until then writeup.state is queued, processing or failed. Refused while
        scrap's Claude is off, and for a page with no image that has been read, or
        whose image is a list of actions. A board gets one on its own; any other page
        only by this tool or the page's Generate button."""
        key = text(page_key(page), "page")
        if not enrich_on():
            raise ToolError("scrap's Claude is off (SCRAP_ENRICH): nothing was queued")
        # queued first (it refuses a page with nothing to write up); the guidance is
        # read when the call runs
        done = checked(enrich.regenerate, store, key)
        if guidance is not None:
            checked(enrich.set_guidance, store, key, text(guidance, "guidance"), AUTHOR)
        return {
            "queued": True,
            "page": done["slug"],
            "writeup_state": (done.get("writeup") or {}).get("state"),
        }
