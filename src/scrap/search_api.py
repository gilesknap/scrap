"""The HTTP routes for search: results, their facets, and every tag. Registered by
app.create_app (add_routes)."""

from typing import Any

from fastapi import FastAPI, Query

from . import topic_api
from .store import Store


def add_routes(app: FastAPI, store: Store) -> None:
    @app.get("/api/search")
    def search(
        q: str,
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),  # the next page of results
    ) -> list[dict[str, Any]]:
        """Full-text search over titles, tags, summaries and bodies, with -word,
        "phrase", kind:, tag:, is:, has:, image:, dates and sort:; snippets mark hits
        with <mark>; each hit says whether it is a topic page (topic)."""
        return topic_api.marked(store, store.search(q, limit, offset))

    @app.get("/api/search/facets")
    def facets(q: str, top: int = Query(12, ge=1, le=1000)) -> dict[str, Any]:
        """The kinds and top tags of a search's pages, with counts, to narrow it."""
        return store.facets(q, top)

    @app.get("/api/tags")
    def tags() -> list[list[Any]]:
        """Every tag in use, with how many pages have it."""
        return store.tags()
