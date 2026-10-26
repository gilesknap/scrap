"""The HTTP routes for photo ingest: reprocessing a capture's photos, and the queue's
status and resume. Registered by app.create_app (add_routes)."""

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from . import ingest
from .api_models import Text
from .store import Store


class Reprocess(BaseModel):
    photo: Text | None = None  # one photo's sha256; default all of the capture's
    replace_human: bool = False  # the user confirmed replacing their own drawing


def add_routes(app: FastAPI, store: Store) -> None:
    @app.post("/api/captures/{cid}/reprocess")
    def reprocess(cid: str, ask: Reprocess) -> dict[str, int]:
        """Send a capture's photos (or one) to Claude again, or retry a failed one."""
        added = ingest.reprocess(store, cid.upper(), ask.photo, ask.replace_human)
        if app.state.worker:
            app.state.worker.wake()
        return added

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
