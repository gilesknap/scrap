"""The HTTP route for the store's health checks (#262): GET /api/health, each check's
count, for the PWA's Store health screen (Settings). A check is a search term
(store.health), so the screen runs its search for the pages themselves. Registered by
app.create_app (add_routes)."""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from .store import Store, health


def add_routes(
    app: FastAPI,
    store: Store,
    publishing: Callable[[], dict[str, Any] | None] = lambda: None,
) -> None:
    @app.get("/api/health")
    def store_health() -> dict[str, Any]:
        """Each health check's count of pages (not in the trash), in the order the
        screen lists them: {checks: [{term, count}]}, term as a search takes it
        (is:orphan, is:untagged, is:stale, is:duplicate, has:dangling,
        is:outdated). One query a check; nothing stored, no model call. publish:
        the public pages' state (Publisher.health), never a failed check."""
        with store.connect() as conn:
            checks = health.counts(conn, store.prompts)
        return {"checks": checks, "publish": publishing()}
