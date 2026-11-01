"""The HTTP routes for public pages (ADR 43; docs/reference/public-site.md, "The PWA's
API in scrap"): PUT /api/pages/{key}/published (publish a page the PWA rendered),
GET /api/public (the public pages, or those linking to one) and
POST /api/public/rebuild (the index units once, after Refresh all). Only under /api,
the owner's PWA session: no /mcp route publishes HTML. Errors are
{"error", "detail"}. Registered by app.create_app (add_routes)."""

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool, StrictInt, ValidationError

from .api_models import Text
from .publish import BadRequest, Busy, Publisher, PublishError, Stale, TooLarge
from .publish.files import MAX_FILES

__all__ = ["MAX_BODY", "add_routes"]

MAX_BODY = 25 * 2**20  # a publish's JSON body


class Drawing(BaseModel):
    """A drawing the page shows (#520): its id, and its SVG from Excalidraw with the
    scene embedded (exportEmbedScene)."""

    key: str = Field(pattern=r"^[1-9][0-9]{0,17}$")
    svg: Text


class Diagram(BaseModel):
    """A Mermaid diagram the page shows (#525): its key (scrap-diagram:<key>-light
    and -dark in the page), and its SVGs in the light and the dark theme."""

    key: str = Field(pattern=r"^[1-9][0-9]{0,2}$")
    light: Text
    dark: Text


class Publish(BaseModel):
    html: Text
    base_rev: StrictInt = Field(ge=0)
    defer: StrictBool = False
    confirmed: StrictBool = False  # needed for a first publish (no kept copy)
    drawings: list[Drawing] = Field(default_factory=list, max_length=MAX_FILES)
    diagrams: list[Diagram] = Field(default_factory=list, max_length=MAX_FILES)


def error(e: PublishError) -> JSONResponse:
    body: dict[str, Any] = {"error": e.code, "detail": e.detail}
    if isinstance(e, Stale):
        body["rev"] = e.rev
    headers = {"Retry-After": str(e.retry_after)} if isinstance(e, Busy) else None
    return JSONResponse(body, e.status, headers)


def add_routes(app: FastAPI, publisher: Publisher) -> None:
    app.add_exception_handler(PublishError, lambda r, e: error(e))  # type: ignore[arg-type]

    @app.put("/api/pages/{key}/published")
    async def published(key: str, request: Request) -> dict[str, Any]:
        """Publish a page: {html, base_rev, defer, drawings, diagrams} from the
        PWA's publish mode, checked and pushed under scrap's lock. 200 {url,
        published_at, files}. A page with no kept copy (never published, or
        unpublished since) needs "confirmed": true, else 409 unconfirmed."""
        length = request.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > MAX_BODY:
            raise TooLarge(f"a publish is at most {MAX_BODY // 2**20} MiB")
        raw = bytearray()
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > MAX_BODY:
                raise TooLarge(f"a publish is at most {MAX_BODY // 2**20} MiB")
        try:
            ask = Publish.model_validate(json.loads(raw))
        except (ValueError, ValidationError) as e:
            raise BadRequest(
                "expected JSON {html, base_rev, defer, confirmed, drawings, diagrams}:"
                f" {str(e)[:200]}"
            ) from None
        drawings = {d.key: d.svg for d in ask.drawings}
        if len(drawings) != len(ask.drawings):
            raise BadRequest("a drawing sent twice")
        diagrams = {d.key: (d.light, d.dark) for d in ask.diagrams}
        if len(diagrams) != len(ask.diagrams):
            raise BadRequest("a diagram sent twice")
        return await run_in_threadpool(
            publisher.publish, key, ask.html, ask.base_rev, ask.defer, ask.confirmed,
            drawings, diagrams,
        )  # fmt: skip

    @app.get("/api/public")
    def public(links_to: str | None = None) -> list[dict[str, Any]]:
        """The public pages not in the trash, [{id, slug, title, published_at}]; with
        links_to=<slug>, only those whose published copy refers to that page."""
        return publisher.public(links_to)

    @app.post("/api/public/rebuild")
    def rebuild() -> dict[str, Any]:
        """Build home, the tag units, search and assets once, and push those whose
        digest changed: {units: [...]}, and "derived": "pending" if the search index
        could not be built."""
        return publisher.rebuild()
