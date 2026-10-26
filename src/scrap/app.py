"""The scrap web application: a JSON API over the store. create_app wires it up; the
routes are in the *_api modules, the PWA in pwa."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import (
    __version__,
    blobs_api,
    captures_api,
    drawing,
    enrich,
    health_api,
    ingest,
    ingest_api,
    mcp_server,
    pages_api,
    photos_api,
    pwa,
    search_api,
    topic_api,
    writeup_api,
)
from .api_models import SURROGATE_MSG, EnrichOffError
from .blobs_api import attachment
from .middleware import BodyLimit, TextGzip
from .pwa import ORIGINS_SLOT, VERSION_SLOT
from .store import (
    ConflictError,
    InvalidError,
    NotFoundError,
    Store,
    TooLargeError,
    now,
    upload_limit,
)

# attachment and the slots: re-exported, where they were before the routes moved out
__all__ = ["create_app", "attachment", "ORIGINS_SLOT", "VERSION_SLOT"]


ERRORS = {
    NotFoundError: 404,
    ConflictError: 409,
    EnrichOffError: 409,
    TooLargeError: 413,
    InvalidError: 422,
}


def create_app(data_dir: Path | str | None = None) -> FastAPI:
    """Build the app on a data folder (default $SCRAP_DATA_DIR, else ./data)."""
    store = Store(data_dir or os.environ.get("SCRAP_DATA_DIR", "data"))
    store.migrate()
    store.prompts = enrich.prompt_versions()  # what is:outdated compares with
    limit = upload_limit()
    worker = ingest.Worker(store) if ingest.enabled() else None
    # MCP at /mcp: stateless (each POST stands alone: a restart drops no session),
    # JSON replies, Host and Origin checked against loopback and $SCRAP_PUBLIC_URL
    tools = mcp_server.server(store)
    mcp_routes = tools.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        max_request_body_size=mcp_server.MAX_REQUEST,
        transport_security=mcp_server.security(mcp_server.public_urls()),
    ).routes

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if worker:
            worker.start()
        try:
            async with tools.session_manager.run():
                yield
        finally:
            if worker:
                worker.stop()

    app = FastAPI(title="scrap", version=__version__, lifespan=lifespan)
    app.state.worker = worker
    app.add_middleware(BodyLimit, limit=limit)
    app.add_middleware(TextGzip)
    if bearer := mcp_server.tokens():  # added last, so outermost: before any work
        app.add_middleware(mcp_server.BearerAuth, tokens=bearer)

    for exc, status in ERRORS.items():

        def handler(request: Request, error: Exception, status: int = status):
            detail: dict[str, Any] = {"detail": str(error) or type(error).__doc__}
            if isinstance(error, (drawing.StaleError, enrich.StaleWriteupError)):
                detail = {"detail": type(error).__doc__, "version": error.args[0]}
            elif isinstance(error, ConflictError):
                detail = {"detail": type(error).__doc__, "rev": error.args[0]}
            return JSONResponse(detail, status)

        app.add_exception_handler(exc, handler)

    def place(error: Any) -> list[Any]:
        """Where an error is; a map key that is itself the bad text is not named."""
        loc = list(error["loc"])
        if SURROGATE_MSG in error["msg"] and "fields" in loc:
            loc = loc[: loc.index("fields") + 1] + ["*"]
        return loc

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        """422 as FastAPI's, without each error's input: 1e400 parses to infinity, which
        JSON cannot carry back (that would be a 500)."""
        detail = [
            {"type": e["type"], "loc": place(e), "msg": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse({"detail": detail}, 422)

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        """Liveness check, plus the upload limit so the PWA can check before sending.
        503 if the ingest worker has stopped. `paused` is why the Claude queue is
        paused (credit, auth, budget, outage), else null."""
        status, code = "ok", 200
        if app.state.worker and not app.state.worker.alive():
            status, code = "ingest worker stopped", 503
        paused = None
        try:  # a probe must not fail on the queue: only say why it is paused
            with store.connect() as conn:
                q = conn.execute(
                    "SELECT paused_until, reason FROM queue_state"
                ).fetchone()
            if q["paused_until"] and q["paused_until"] > now():
                paused = q["reason"]
        except Exception:
            logging.getLogger(__name__).exception("healthz: queue state unreadable")
        body = {"status": status, "version": __version__, "max_upload_bytes": limit,
                "paused": paused}  # fmt: skip
        return JSONResponse(body, code)

    pages_api.add_routes(app, store, limit)

    def wake() -> None:
        if app.state.worker:
            app.state.worker.wake()

    writeup_api.add_routes(app, store, wake)
    topic_api.add_routes(app, store, wake)
    photos_api.add_routes(app, store, wake, limit)
    health_api.add_routes(app, store)
    captures_api.add_routes(app, store)
    ingest_api.add_routes(app, store)
    search_api.add_routes(app, store)
    blobs_api.add_routes(app, store)

    app.router.routes.extend(mcp_routes)  # before the PWA's catch-all mount
    pwa.add_routes(app)

    return app
