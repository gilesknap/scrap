"""The scrap web application: a JSON API over the store."""

import json
import logging
import mimetypes
import os
import re
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import anyio
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
from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt
from starlette.datastructures import UploadFile
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__, backup, drawing, ingest, preview
from .store import (
    MAX_FIELDS,
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
SCENE_REQUEST = 8 * 2**20  # a 5 MB scene, plus the files map it may carry (dropped)
APP_ROUTES = ("/", "/recent", "/search", "/p/{key}")  # served index.html
NOT_BUILT = (
    "The scrap PWA is not built. Run: npm --prefix web ci && npm --prefix web run build"
    "\n(the API under /api works without it)\n"
)


class Reprocess(BaseModel):
    photo: str | None = None  # one photo's sha256; default all of the capture's
    replace_human: bool = False  # the user confirmed replacing their own drawing


VERSION_NUMBER = Annotated[StrictInt, Field(ge=1, le=2**31)]


class Drawing(JSONResponse):
    """A drawing as JSON. A stored row that cannot be encoded (rows made before the
    sanitiser refused lone surrogates) is served with them replaced, and logged,
    rather than failing every request for it."""

    def render(self, content: Any) -> bytes:
        try:
            return super().render(content)
        except UnicodeEncodeError:
            logging.getLogger(__name__).warning("drawing with unencodable text served")
            text = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
            return text.encode("utf-8", errors="replace")


class Restore(BaseModel):
    version: VERSION_NUMBER  # the version to make current again
    base_version: VERSION_NUMBER  # the current one as the client saw it, else 409


FIELD_NAME = Annotated[str, Field(min_length=1, max_length=40)]
# A field's value: flat, as the importer stores them too (None in a PATCH drops it)
FIELD = Annotated[str, Field(max_length=200)] | StrictBool | StrictInt | StrictFloat


class PageEdit(BaseModel):
    base_rev: int | None = None  # needed with a title or body
    title: str | None = None
    body: str | None = None
    kind: str | None = None  # one the user chose: fixed, ingest keeps it
    fields: (
        Annotated[dict[FIELD_NAME, FIELD | None], Field(max_length=MAX_FIELDS)] | None
    ) = None


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


class TextGzip:
    """Gzip what compresses: the PWA's scripts, styles and pages, and the API's JSON
    (a drawing is up to 5 MB of it). Not files (blobs, previews, downloads: photos and
    zips are compressed already, and they take range requests), nor fonts or images
    (excluded by type), nor any range request."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1024, compresslevel=6)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        files = path.startswith("/api/blobs/") or path.endswith("/download")
        ranged = any(k == b"range" for k, _ in scope.get("headers", ()))
        if scope["type"] != "http" or files or ranged:
            await self.app(scope, receive, send)
        else:
            await self.gzip(scope, receive, send)


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
    worker = ingest.Worker(store) if ingest.enabled() else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if worker:
            worker.start()
        yield
        if worker:
            worker.stop()

    app = FastAPI(title="scrap", version=__version__, lifespan=lifespan)
    app.state.worker = worker
    app.add_middleware(BodyLimit, limit=limit)
    app.add_middleware(TextGzip)

    for exc, status in ERRORS.items():

        def handler(request: Request, error: Exception, status: int = status):
            detail: dict[str, Any] = {"detail": str(error) or type(error).__doc__}
            if isinstance(error, drawing.StaleError):
                detail = {"detail": type(error).__doc__, "version": error.args[0]}
            elif isinstance(error, ConflictError):
                detail = {"detail": type(error).__doc__, "rev": error.args[0]}
            return JSONResponse(detail, status)

        app.add_exception_handler(exc, handler)

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        """Liveness check, plus the upload limit so the PWA can check before sending.
        503 if the ingest worker has stopped."""
        status, code = "ok", 200
        if app.state.worker and not app.state.worker.alive():
            status, code = "ingest worker stopped", 503
        body = {"status": status, "version": __version__, "max_upload_bytes": limit}
        return JSONResponse(body, code)

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
        saved = store.capture(capture, blobs, who)
        if app.state.worker:
            app.state.worker.wake()
        return saved

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
    def recent(
        limit: int = Query(50, ge=1, le=500),
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Pages, most recently changed first; the trash is left out. Only those of
        one kind, if given (empty: all)."""
        return store.recent(limit, kind or None)

    @app.get("/api/pages/{key}")
    def page(key: str) -> dict[str, Any]:
        """A page by id or slug, with its captures and their files."""
        return store.page(key)

    @app.patch("/api/pages/{key}")
    def edit(key: str, edit: PageEdit, request: Request) -> dict[str, Any]:
        """Change title and/or body (409 if base_rev is not the current revision),
        and/or the kind and fields."""
        if edit.base_rev is None and (edit.title, edit.body) != (None, None):
            raise InvalidError("base_rev is needed to change the title or body")
        who = author(request)
        return store.update_page(
            key, edit.base_rev, edit.title, edit.body, who, edit.kind, edit.fields
        )

    @app.delete("/api/pages/{key}", status_code=204)
    def delete(key: str) -> None:
        """Move a page to the trash."""
        store.delete_page(key)

    @app.post("/api/pages/{key}/undelete")
    def undelete(key: str) -> dict[str, Any]:
        """Bring a page back from the trash."""
        store.delete_page(key, undo=True)
        return store.page(key)

    @app.post("/api/captures/{cid}/reprocess")
    def reprocess(cid: str, ask: Reprocess) -> dict[str, int]:
        """Send a capture's photos (or one) to Claude again, or retry a failed one."""
        added = ingest.reprocess(store, cid.upper(), ask.photo, ask.replace_human)
        if app.state.worker:
            app.state.worker.wake()
        return added

    def photo(cid: str, sha: str) -> tuple[str, str]:
        return cid.upper(), sha.lower()

    # The drawing endpoints answer with Drawing (a JSONResponse): a scene is JSON from
    # the editor, passed through as stored, not a model for FastAPI to check again.
    @app.get("/api/captures/{cid}/photos/{sha}/drawing")
    def drawing_current(cid: str, sha: str) -> Drawing:
        """A photo's current drawing, with its data; 404 if it has none."""
        return Drawing(drawing.current(store, *photo(cid, sha)))

    @app.get("/api/captures/{cid}/photos/{sha}/drawing/versions")
    def drawing_versions(cid: str, sha: str) -> Drawing:
        """Every version of a photo's drawing, newest first, without their data."""
        return Drawing(drawing.versions(store, *photo(cid, sha)))

    @app.put("/api/captures/{cid}/photos/{sha}/drawing")
    async def drawing_save(cid: str, sha: str, request: Request) -> Drawing:
        """Save a scene from the editor as a new human version: {base_version, scene}.
        409 if the current version is no longer base_version, 422 if the scene breaks
        a rule, 413 if the request is over SCENE_REQUEST bytes."""
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > SCENE_REQUEST:
                raise TooLargeError(too_large(SCENE_REQUEST))
        try:
            ask = json.loads(body)
        except (ValueError, RecursionError):  # also nesting or digits past the parser's
            raise InvalidError("expected JSON") from None
        if not isinstance(ask, dict) or not (
            ask.get("base_version") is None or type(ask["base_version"]) is int
        ):
            raise InvalidError("expected {base_version, scene}")
        who = author(request)
        saved = await run_in_threadpool(
            drawing.save, store, *photo(cid, sha), ask["base_version"],
            ask.get("scene"), who,
        )  # fmt: skip
        return Drawing(saved)

    @app.post("/api/captures/{cid}/photos/{sha}/drawing/restore")
    def drawing_restore(cid: str, sha: str, ask: Restore, request: Request) -> Drawing:
        """Make an old version of the drawing current again, as a new copy; 409 if
        base_version is no longer current, 404 if there is no such version."""
        who = author(request)
        restored = drawing.restore(
            store, *photo(cid, sha), ask.version, ask.base_version, who
        )
        return Drawing(restored)

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

    decoding = anyio.Lock()  # requests wait for the decoder here, not in worker threads

    @app.get("/api/blobs/{sha}/preview")
    async def blob_preview(sha: str, size: int = 2048) -> Response:
        """A JPEG preview of a stored photo (HEIC too), turned upright, at most size
        (480 or 2048) pixels a side; made on first request, then cached. 503 while
        the decoder is busy for long."""
        busy = JSONResponse(
            {"detail": preview.BusyError.__doc__}, 503, {"Retry-After": "5"}
        )
        path = await run_in_threadpool(preview.cached, store, sha, size)
        if path is None:
            try:
                with anyio.fail_after(preview.WAIT):
                    await decoding.acquire()
            except TimeoutError:
                return busy
            try:
                path = await run_in_threadpool(preview.preview, store, sha, size)
            except preview.BusyError:  # another caller of preview() has the decoder
                return busy
            finally:
                decoding.release()
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
