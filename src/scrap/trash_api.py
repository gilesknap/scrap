"""The HTTP route for the trash (#276): GET /api/trash, the pages in it with when each
is purged, for the PWA's Trash screen (Settings). Bringing one back is
POST /api/pages/{key}/undelete. Registered by app.create_app (add_routes)."""

from typing import Any

from fastapi import FastAPI, Query

from .store import Store
from .store.trash import trash_days


def add_routes(app: FastAPI, store: Store) -> None:
    trash_days()  # a bad SCRAP_TRASH_DAYS stops the start, not a request

    @app.get("/api/trash")
    def trash(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
        """The pages in the trash, most recently deleted first: {days, results}.
        days is how long a page stays there (SCRAP_TRASH_DAYS; null: never purged);
        each result is {id, slug, title, kind, deleted_at, updated_at, topic,
        purge_at}: purge_at is when the nightly gc purges it from then on, null for a
        topic (kept: its key stops Claude making the topic again) or with purging
        off."""
        return {"days": trash_days(), "results": store.trash(limit)}
