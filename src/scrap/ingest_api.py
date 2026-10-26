"""The HTTP routes for the ingest queue: its status, and resuming it. Registered by
app.create_app (add_routes)."""

from typing import Any

from fastapi import FastAPI

from . import ingest
from .store import Store


def add_routes(app: FastAPI, store: Store) -> None:
    @app.get("/api/ingest")
    def ingest_status() -> dict[str, Any]:
        """The ingest queue: paused or not (and why), jobs by state, spend today."""
        return ingest.status(store)

    @app.post("/api/ingest/resume")
    def resume() -> dict[str, Any]:
        """End a pause of the ingest queue."""
        ingest.resume_queue(store)
        if app.state.worker:
            app.state.worker.wake()
        return ingest.status(store)
