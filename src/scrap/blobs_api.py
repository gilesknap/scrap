"""The HTTP routes for files: a page's download, the whole store's export, and a
stored file, its preview and how many pages use it. Registered by app.create_app
(add_routes)."""

import re
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote

import anyio
from fastapi import FastAPI, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import backup, export, preview
from .store import Store

BLOB_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",  # an uploaded HTML file cannot run scripts
    "Cache-Control": "private, max-age=31536000, immutable",
}


def attachment(name: str) -> str:
    """Content-Disposition saving a file as name: ASCII fallback, then RFC 5987."""
    plain = name.encode("ascii", "replace").decode().replace("?", "_")
    plain = re.sub(r'["\\\x00-\x1f\x7f]', "_", plain)
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='')}"


def add_routes(app: FastAPI, store: Store) -> None:
    @app.get("/api/pages/{key}/download")
    def page_download(
        key: str,
        notes: bool = True,
        photos: Literal["original", "preview"] = "original",
    ) -> Response:
        """A page as <slug>.md, or with its files a <slug>.zip. notes=0 leaves out
        Claude's notes; photos=preview has each photo as its 2048 pixel JPEG preview,
        which carries no EXIF or GPS (what Share sends).
        503 while the decoder is busy."""
        out = tempfile.SpooledTemporaryFile(max_size=8 * 2**20)
        try:
            name, mime = backup.download(store, key, out, notes, photos == "preview")
        except preview.BusyError:
            out.close()
            return JSONResponse(
                {"detail": preview.BusyError.__doc__}, 503, {"Retry-After": "5"}
            )
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

    @app.get("/api/store/download")
    def store_download() -> StreamingResponse:
        """Every page as Markdown with its files, as scrap-export-<date>.zip, streamed
        as it is made (export.py; Settings > Export everything). The pages are read
        first, in one transaction; then the files follow, a chunk at a time."""
        name = f"scrap-export-{datetime.now(UTC).date().isoformat()}.zip"
        headers = {"Content-Disposition": attachment(name), "Cache-Control": "no-store"}
        return StreamingResponse(
            export.stream(store), media_type="application/zip", headers=headers
        )

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

    @app.get("/api/blobs/{sha}/uses")
    def blob_uses(sha: str, page: str) -> dict[str, int]:
        """How many other pages show a stored file (the trash left out), for the
        editor's warning when its embed is deleted from page (an id)."""
        return {"pages": store.blob_uses(sha.lower(), page)}

    @app.get("/api/blobs/{sha}")
    def blob(sha: str, download: bool = False) -> FileResponse:
        """A stored original, byte for byte; ?download=1 saves it under its name."""
        path, mime = store.blob(sha)
        headers = dict(BLOB_HEADERS)
        if download:
            name = backup.file_name(store.blob_name(sha), sha, mime)
            headers["Content-Disposition"] = attachment(name)
        return FileResponse(path, media_type=mime, headers=headers)
