"""The scrap web application: a JSON API over the store."""

import logging
import mimetypes
import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.datastructures import UploadFile
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__, backup, preview
from .store import (
    ConflictError,
    InvalidError,
    NotFoundError,
    Store,
    TooLargeError,
    new_ulid,
)

__all__ = ["create_app"]

ERRORS = {NotFoundError: 404, ConflictError: 409, TooLargeError: 413, InvalidError: 422}
BLOB_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",  # an uploaded HTML file cannot run scripts
    "Cache-Control": "private, max-age=31536000, immutable",
}
SHARED_LINK = re.compile(r"(?:^|\s)(https?://\S+)$")
STATIC = Path(__file__).parent / "static"  # the built PWA (npm --prefix web run build)
APP_ROUTES = ("/", "/recent", "/search", "/p/{key}")  # served index.html
NOT_BUILT = (
    "The scrap PWA is not built. Run: npm --prefix web ci && npm --prefix web run build"
    "\n(the API under /api works without it)\n"
)


class PageEdit(BaseModel):
    base_rev: int
    title: str | None = None
    body: str | None = None


def author(request: Request) -> str:
    # Set by Tailscale Serve; tagged devices (and anything else) send none.
    return request.headers.get("Tailscale-User-Login") or "tagged"


def attachment(name: str) -> str:
    """Content-Disposition saving a file as name: ASCII fallback, then RFC 5987."""
    plain = name.encode("ascii", "replace").decode().replace("?", "_")
    plain = re.sub(r'["\\\x00-\x1f\x7f]', "_", plain)
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='')}"


def too_large(limit: int) -> str:
    return f"over the {limit / 2**20:g} MB upload limit"


class BodyLimit:
    """Raise TooLargeError while a request body is read, once it passes limit bytes.

    Covers chunked bodies with no Content-Length; the route turns it into a 413.
    """

    def __init__(self, app: ASGIApp, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b""))
            if seen > self.limit:
                raise TooLargeError(too_large(self.limit))
            return message

        await self.app(scope, counted, send)


class Shell(StaticFiles):
    """The built PWA. Hashed assets are cached for good; the rest is revalidated, so
    a new build's service worker and manifest are noticed."""

    def file_response(self, full_path, *args, **kwargs):
        response = super().file_response(full_path, *args, **kwargs)
        immutable = "/assets/" in str(full_path)
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if immutable else "no-cache"
        )
        return response


def create_app(data_dir: Path | str | None = None) -> FastAPI:
    """Build the app on a data folder (default $SCRAP_DATA_DIR, else ./data)."""
    store = Store(data_dir or os.environ.get("SCRAP_DATA_DIR", "data"))
    store.migrate()
    limit = int(float(os.environ.get("SCRAP_MAX_UPLOAD_MB", "50")) * 2**20)
    app = FastAPI(title="scrap", version=__version__)
    app.add_middleware(BodyLimit, limit=limit)

    for exc, status in ERRORS.items():

        def handler(request: Request, error: Exception, status: int = status):
            detail: dict[str, Any] = {"detail": str(error) or type(error).__doc__}
            if isinstance(error, ConflictError):
                detail = {"detail": type(error).__doc__, "rev": error.args[0]}
            return JSONResponse(detail, status)

        app.add_exception_handler(exc, handler)

    @app.get("/healthz")
    def healthz() -> dict[str, str | int]:
        """Liveness check, plus the upload limit so the PWA can check before sending."""
        return {"status": "ok", "version": __version__, "max_upload_bytes": limit}

    def save(data: dict[str, Any], uploads: list[UploadFile], who: str):
        mimes = []
        for upload in uploads:
            mime = upload.content_type
            if mime in (None, "", "application/octet-stream"):
                mime = mimetypes.guess_type(upload.filename or "")[0]
            mimes.append(mime or "application/octet-stream")
        capture = store.prepare(data, mimes)  # before writing any file
        blobs = []
        for upload, mime in zip(uploads, mimes, strict=True):
            sha, size = store.put_blob(upload.file)
            blobs.append((sha, mime, size, upload.filename or None))
        return store.capture(capture, blobs, who)

    @app.post("/api/captures", status_code=201)
    async def capture(request: Request, response: Response) -> dict[str, str]:
        """Save a note, link, photo or file; a retry with the same id returns 200."""
        if int(request.headers.get("content-length") or 0) > limit:
            raise TooLargeError(too_large(limit))
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

    @app.post("/share", include_in_schema=False)
    async def share(request: Request) -> RedirectResponse:
        """The manifest share target, if the service worker did not catch the POST
        (it normally queues the share itself): save it as a capture now."""
        who = author(request)
        async with request.form() as form:
            fields = {k: v.strip() for k, v in form.items() if isinstance(v, str)}
            title, text, url = (fields.get(k, "") for k in ("title", "text", "url"))
            # As the service worker does: Android sends a link as text after the title
            if not url and (link := SHARED_LINK.search(text)):
                url, text = link[1], text[: link.start()].strip()
            if title and title not in text:
                text = f"{title}\n\n{text}".strip()
            data = {"id": new_ulid(), "text": text, "url": url, "source": "share"}
            files = [
                f for f in form.getlist("files") if isinstance(f, UploadFile) and f.size
            ]
            if text or url or files:
                await run_in_threadpool(save, data, files, who)
        return RedirectResponse("/", 303)

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

    @app.post("/api/pages/{key}/undelete")
    def undelete(key: str) -> dict[str, Any]:
        """Bring a page back from the trash."""
        store.delete_page(key, undo=True)
        return store.page(key)

    @app.get("/api/search")
    def search(q: str, limit: int = Query(20, ge=1, le=100)) -> list[dict[str, Any]]:
        """Full-text search over titles and bodies; snippets mark hits with <mark>."""
        return store.search(q, limit)

    @app.get("/api/pages/{key}/download")
    def page_download(key: str) -> StreamingResponse:
        """A page as <slug>.md, or with its files a <slug>.zip."""
        out = tempfile.SpooledTemporaryFile(max_size=8 * 2**20)
        try:
            name, mime = backup.download(store, key, out)
        except BaseException:
            out.close()
            raise
        out.seek(0)

        def chunks() -> Iterator[bytes]:
            with out:
                while chunk := out.read(1 << 16):
                    yield chunk

        headers = {"Content-Disposition": attachment(name), "Cache-Control": "no-store"}
        return StreamingResponse(chunks(), media_type=mime, headers=headers)

    @app.get("/api/blobs/{sha}/preview")
    def blob_preview(sha: str, size: int = 2048) -> Response:
        """A JPEG preview of a stored photo (HEIC too), turned upright, at most size
        (480 or 2048) pixels a side; made on first request, then cached. 503 while
        the decoder is busy for long."""
        try:
            path = preview.preview(store, sha, size)
        except preview.BusyError as error:
            return JSONResponse({"detail": error.__doc__}, 503, {"Retry-After": "5"})
        return FileResponse(path, media_type="image/jpeg", headers=BLOB_HEADERS)

    @app.get("/api/blobs/{sha}")
    def blob(sha: str, download: bool = False) -> FileResponse:
        """A stored original, byte for byte; ?download=1 saves it under its name."""
        path, mime = store.blob(sha)
        headers = dict(BLOB_HEADERS)
        if download:
            name = backup.file_name(store.blob_name(sha), sha, mime)
            headers["Content-Disposition"] = attachment(name)
        return FileResponse(path, media_type=mime, headers=headers)

    # $SCRAP_WEB_DIR serves a PWA build from elsewhere, e.g. one being tried out live
    static = Path(os.environ.get("SCRAP_WEB_DIR") or STATIC)
    index = static / "index.html"
    if not index.is_file():
        logging.getLogger(__name__).warning(NOT_BUILT.splitlines()[0])

    def shell() -> Response:
        """The PWA: every app route loads index.html and routes in the browser."""
        if not index.is_file():
            return PlainTextResponse(NOT_BUILT, 503)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    for route in APP_ROUTES:
        app.get(route, include_in_schema=False)(shell)
    if static.is_dir():
        app.mount("/", Shell(directory=static), name="static")

    return app
