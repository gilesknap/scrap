"""The HTTP routes for a board page's write-up (#256): Regenerate, the owner's
guidance, its versions and Restore. Registered by app.create_app (add_routes)."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from . import enrich
from .api_models import EnrichOffError, Restore, Text
from .store import Store, enrich_on
from .uploads import author


class Guidance(BaseModel):
    # The owner's note for the next write-up; empty or null: none
    guidance: Annotated[Text, Field(max_length=enrich.MAX_GUIDANCE)] | None = None


def add_routes(app: FastAPI, store: Store, wake: Callable[[], None]) -> None:
    @app.post("/api/pages/{key}/writeup")
    def writeup_regenerate(key: str) -> dict[str, Any]:
        """Queue a board page's write-up again (Regenerate), with its guidance: the
        page as it is; 409 while Claude is off, 422 if it has no whiteboard or
        diagram image."""
        if not enrich_on():
            raise EnrichOffError
        page = enrich.regenerate(store, key)
        wake()
        return page

    @app.put("/api/pages/{key}/writeup/guidance")
    def writeup_guidance(key: str, ask: Guidance, request: Request) -> dict[str, Any]:
        """Keep the owner's guidance for a page's next write-up (empty or null: none),
        stored apart from its text; the page. It queues nothing: Regenerate does."""
        return enrich.set_guidance(store, key, ask.guidance, author(request))

    @app.get("/api/pages/{key}/writeup/versions")
    def writeup_versions(key: str) -> list[dict[str, Any]]:
        """Every write-up of a page, newest first, with its text and whether it is
        current."""
        return enrich.versions(store, key)

    @app.post("/api/pages/{key}/writeup/restore")
    def writeup_restore(key: str, ask: Restore) -> dict[str, Any]:
        """Make an old write-up current again, as a new copy; the page. 409 if
        base_version is no longer current, 404 if there is no such version."""
        return enrich.restore(store, key, ask.version, ask.base_version)
