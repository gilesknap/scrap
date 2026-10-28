"""The write tool: add a page, or append to one written over MCP."""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..mcp_page import page_key
from ..store import (
    KIND_NAMES,
    KINDS,
    MAX_PAGE,
    MCP,
    check_todo,
    clean_tags,
    fields_for,
    new_ulid,
    now,
)
from .context import Ctx, key_id, text
from .limits import (
    AUTHOR,
    MAX_BODY,
    MAX_KEY,
    MAX_ORIGIN,
    MAX_TAGS,
    MAX_TITLE,
    STATUSES,
    WRITE_KINDS,
)


def register_writing(mcp: MCPServer, ctx: Ctx) -> None:
    """write."""
    store = ctx.store
    link = ctx.link
    checked = ctx.checked

    @mcp.tool()
    def write(
        title: Annotated[str, Field(max_length=MAX_TITLE)],
        body: str,
        origin: Annotated[
            str,
            Field(
                max_length=MAX_ORIGIN,
                description="Where this comes from: repo or directory, and date",
            ),
        ],
        tags: Annotated[list[str], Field(max_length=MAX_TAGS)] = [],  # noqa: B006
        kind: Annotated[str, Field(description="note, todo, read, board or doc")] = (
            "note"
        ),
        status: Annotated[
            str | None, Field(description="open, in_progress, done, cancelled")
        ] = None,
        due: Annotated[
            str | None,
            Field(description="A todo's due date, YYYY-MM-DD (none: clear it)"),
        ] = None,
        priority: Annotated[
            str | None,
            Field(description="A todo's priority: high, medium, low (none: clear)"),
        ] = None,
        append_to: Annotated[
            str | None,
            Field(
                description="Id, slug or URL of a page written over MCP to append to"
            ),
        ] = None,
        key: Annotated[
            str | None,
            Field(
                max_length=MAX_KEY,
                description="Idempotency key: a retry with the same key adds nothing",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Save a new page (Markdown body; [[slug|label]] links to other pages), marked
        as written by Claude with its origin; a todo may have a due date and
        priority.
        With append_to, add body as a new section at the end of a page written over
        MCP instead (the user's own pages cannot be changed), and set its due date or
        priority if given (a todo's; body may then be empty). Returns the page's id,
        slug and URL."""
        body = text(body, "body").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(body.encode()) > MAX_BODY:
            raise ToolError(f"body is over {MAX_BODY} bytes")
        origin = " ".join(text(origin, "origin").split())
        title = " ".join(text(title, "title").split())
        cleaned = checked(clean_tags, [text(t, "a tag") for t in tags], MAX_TAGS)
        key = text(key, "key") if key else None
        cid = key_id(key) if key else new_ulid()
        # a todo's due date and priority, those given ("none" clears one on append)
        given = (("due", due), ("priority", priority))
        todo = {k: None if v == "none" else v for k, v in given if v}
        if append_to:
            append_to = text(page_key(append_to), "append_to")
            if not body and not todo:
                raise ToolError("nothing to append")
            if key:  # keyed by the page itself, whether named by id or slug
                cid = key_id(key, checked(store.page, append_to)["id"])
            ref, new = checked(
                store.append, append_to, cid, body, AUTHOR, cleaned, MAX_PAGE, todo
            )
        else:
            if not title:
                raise ToolError("title must not be empty")
            if kind not in WRITE_KINDS and kind not in KINDS:
                raise ToolError(f"kind must be one of {WRITE_KINDS}")
            kind = KIND_NAMES.get(kind, kind)
            fields = fields_for(kind, None)
            if status is not None:
                if "status" not in fields or status not in STATUSES:
                    raise ToolError(f"status is for todo and read: one of {STATUSES}")
                fields["status"] = status
            if origin:
                fields["origin"] = origin
            if any(todo.values()) and kind != "todo":
                raise ToolError("due and priority are for todos")
            for name, value in todo.items():
                checked(check_todo, name, value)
            stamp = now()
            capture = {
                "id": cid, "kind": "note", "text": body or None, "url": None,
                "source": MCP, "created_at": stamp, "page_kind": kind,
                "fields": fields, "title": title, "body": body, **todo,
            }  # fmt: skip
            ref, new = store.capture(capture, [], AUTHOR, cleaned)
        return {
            "id": ref["page_id"],
            "slug": ref["slug"],
            "url": link(ref["slug"]),
            "created": new,  # False: a retry with the same key, nothing added
        }
