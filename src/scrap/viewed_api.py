"""The HTTP route the PWA reports a page opening to (#452), for MCP current_page.
Registered by app.create_app (add_routes)."""

from fastapi import FastAPI

from . import viewed
from .store import Store


def add_routes(app: FastAPI, store: Store) -> None:
    @app.post("/api/pages/{key}/viewed", status_code=204)
    def page_viewed(key: str) -> None:
        """Record that the user opened the page (id or slug): the one most recently
        opened, on any device, kept in memory only. 404 for a page that is gone or
        in the trash."""
        viewed.record(store.page(key)["id"])
