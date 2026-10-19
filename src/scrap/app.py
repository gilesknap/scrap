"""The scrap web application: a JSON API over the store."""

import mimetypes
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from . import __version__
from .store import ConflictError, InvalidError, NotFoundError, Store, TooLargeError

__all__ = ["create_app"]

ERRORS = {NotFoundError: 404, ConflictError: 409, TooLargeError: 413, InvalidError: 422}
BLOB_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",  # an uploaded HTML file cannot run scripts
    "Cache-Control": "private, max-age=31536000, immutable",
}


class PageEdit(BaseModel):
    base_rev: int
    title: str | None = None
    body: str | None = None


def author(request: Request) -> str:
    # Set by Tailscale Serve; tagged devices (and anything else) send none.
    return request.headers.get("Tailscale-User-Login") or "tagged"


def create_app(data_dir: Path | str | None = None) -> FastAPI:
    """Build the app on a data folder (default $SCRAP_DATA_DIR, else ./data)."""
    store = Store(data_dir or os.environ.get("SCRAP_DATA_DIR", "data"))
    store.migrate()
    limit = int(float(os.environ.get("SCRAP_MAX_UPLOAD_MB", "50")) * 2**20)
    app = FastAPI(title="scrap", version=__version__)

    for exc, status in ERRORS.items():

        def handler(request: Request, error: Exception, status: int = status):
            detail: dict[str, Any] = {"detail": str(error) or type(error).__doc__}
            if isinstance(error, ConflictError):
                detail["rev"] = error.args[0]  # the current revision
            return JSONResponse(detail, status)

        app.add_exception_handler(exc, handler)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness check: the process is up and serving requests."""
        return {"status": "ok", "version": __version__}

    def save(data: dict[str, Any], uploads: list[UploadFile], who: str):
        blobs, room = [], limit
        for upload in uploads:
            sha, size = store.put_blob(upload.file, room)
            room -= size
            name = upload.filename or ""
            mime = upload.content_type
            if mime in (None, "", "application/octet-stream"):
                mime = mimetypes.guess_type(name)[0]
            blobs.append((sha, mime or "application/octet-stream", size, name or None))
        return store.capture(data, blobs, who)

    @app.post("/api/captures", status_code=201)
    async def capture(request: Request, response: Response) -> dict[str, str]:
        """Save a note, link, photo or file; a retry with the same id returns 200."""
        if int(request.headers.get("content-length") or 0) > limit:
            raise TooLargeError
        who = author(request)
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            async with request.form() as form:  # closes the spooled uploads
                data = {k: v for k, v in form.items() if isinstance(v, str)}
                files = [f for f in form.getlist("file") if isinstance(f, UploadFile)]
                ref, created = await run_in_threadpool(save, data, files, who)
        else:
            try:
                data = await request.json()
            except ValueError:
                raise InvalidError("expected JSON or multipart/form-data") from None
            if not isinstance(data, dict):
                raise InvalidError("expected a JSON object")
            ref, created = await run_in_threadpool(save, data, [], who)
        response.status_code = 201 if created else 200
        return ref

    @app.get("/api/pages")
    def recent(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
        """Pages, most recently changed first; the trash is left out."""
        return store.recent(limit)

    @app.get("/api/pages/{key}")
    def page(key: str) -> dict[str, Any]:
        """A page by id or slug, with its captures and their files."""
        return store.page(key)

    @app.patch("/api/pages/{key}")
    def edit(key: str, edit: PageEdit, request: Request) -> dict[str, Any]:
        """Change title and/or body; 409 if base_rev is not the current revision."""
        who = author(request)
        return store.update_page(key, edit.base_rev, edit.title, edit.body, who)

    @app.delete("/api/pages/{key}", status_code=204)
    def delete(key: str) -> None:
        """Move a page to the trash."""
        store.delete_page(key)

    @app.get("/api/search")
    def search(q: str, limit: int = Query(20, ge=1, le=100)) -> list[dict[str, Any]]:
        """Full-text search over titles and bodies; snippets mark hits with <mark>."""
        return store.search(q, limit)

    @app.get("/api/blobs/{sha}")
    def blob(sha: str) -> FileResponse:
        """A stored original, byte for byte."""
        path, mime = store.blob(sha)
        return FileResponse(path, media_type=mime, headers=BLOB_HEADERS)

    return app
