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
from .publish import BadRequest, Publisher, PublishError, Stale, TooLarge

__all__ = ["MAX_BODY", "add_routes"]

MAX_BODY = 25 * 2**20  # a publish's JSON body


class Publish(BaseModel):
    html: Text
    base_rev: StrictInt = Field(ge=0)
    defer: StrictBool = False
    confirmed: StrictBool = False  # needed for a first publish (no kept copy)


def error(e: PublishError) -> JSONResponse:
    body: dict[str, Any] = {"error": e.code, "detail": e.detail}
    if isinstance(e, Stale):
        body["rev"] = e.rev
    return JSONResponse(body, e.status)


def add_routes(app: FastAPI, publisher: Publisher) -> None:
    app.add_exception_handler(PublishError, lambda r, e: error(e))  # type: ignore[arg-type]

    @app.put("/api/pages/{key}/published")
    async def published(key: str, request: Request) -> dict[str, Any]:
        """Publish a page: {html, base_rev, defer} from the PWA's publish mode, checked
        and pushed under scrap's lock. 200 {url, published_at, files}. A page with
        no kept copy (never published, or unpublished since) needs "confirmed": true,
        else 409 unconfirmed."""
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
                f"expected JSON {{html, base_rev, defer, confirmed}}: {str(e)[:200]}"
            ) from None
        return await run_in_threadpool(
            publisher.publish, key, ask.html, ask.base_rev, ask.defer, ask.confirmed
        )

    @app.get("/api/public")
    def public(links_to: str | None = None) -> list[dict[str, Any]]:
        """The public pages not in the trash, [{id, slug, title, published_at}]; with
        links_to=<slug>, only those whose published copy refers to that page."""
        return publisher.public(links_to)

    @app.post("/api/public/rebuild")
    def rebuild() -> dict[str, Any]:
        """Build home, the tag units, search and assets once, and push those whose
        digest changed: {units: [...]}."""
        return {"units": publisher.rebuild()}
