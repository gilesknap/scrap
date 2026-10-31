"""The HTTP route that adds photos (or PDFs and text files, #234) to a page that
exists (#260): the page editor's Add photo. Registered by app.create_app
(add_routes)."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from .store import MCP, InvalidError, Store, TooLargeError
from .store.constants import SOURCES, ULID
from .store.photos import addable
from .uploads import author, by_mcp, mimes, put_files, too_large

REFUSED = (
    "Only images, PDFs and text files can be added to a page; another file needs a "
    "capture of its own."
)


class NotImageError(Exception):
    """A file that is not an image, a PDF or a text file: 415, REFUSED."""


def fields(form: dict[str, Any]) -> tuple[str, str, str | None]:
    """The form's id, source and created_at, checked."""
    cid = form.get("id") or ""
    source, created = form.get("source") or "pwa", form.get("created_at") or None
    if not ULID.fullmatch(cid.upper()):
        raise InvalidError("id must be a ULID")
    if source not in SOURCES:
        raise InvalidError(f"source must be one of {SOURCES}")
    if created is not None:
        try:
            datetime.fromisoformat(created)
        except ValueError:
            raise InvalidError("created_at must be ISO 8601") from None
    return cid, source, created


def add_routes(
    app: FastAPI, store: Store, wake: Callable[[], None], limit: int
) -> None:
    def refused(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": REFUSED}, 415)

    app.add_exception_handler(NotImageError, refused)

    def save(
        key: str, form: dict[str, Any], uploads: list[UploadFile], who: str,
        claude: bool,
    ) -> dict[str, Any]:  # fmt: skip
        cid, source, created = fields(form)  # before writing any file
        after = (form.get("after") or "").replace("\r\n", "\n").replace("\r", "\n")
        after = after or None  # as the text is stored: LF line ends
        alt = form.get("alt") or ""
        if not uploads:
            raise InvalidError("no photo to add")
        types = mimes(uploads)
        if not all(addable(t) for t in types):
            raise NotImageError
        blobs = put_files(store, uploads, types)
        page, created_now = store.add_photos(
            key, cid, blobs, who, MCP if claude else source, created,
            after=after, alt=alt,
        )  # fmt: skip
        wake()
        base = "/mcp" if claude else "/api"  # where the caller fetches them from
        added = [
            {"sha256": sha, "mime": mime, "filename": name,
             "download_url": f"{base}/blobs/{sha}?download=1"}
            for sha, mime, _, name in blobs
        ]  # fmt: skip
        return {**page, "created": created_now, "added": added}

    @app.post("/api/pages/{key}/captures", status_code=201)
    async def add_photos(key: str, request: Request, response: Response) -> Any:
        """Add photos or files to a page: multipart id (a ULID, the retry key) and file
        parts, images, PDFs and text or Markdown files only (415 otherwise; an untyped
        part is typed by its name; an SVG is stored sanitised, at most 1 MiB). Each new
        image's embed goes to the end of its text as it is now, or after the line the
        optional after field's text ends on (it must occur once), with the optional
        alt field as its alt text, as a new revision; a file is listed below the
        text, not put in it. They are read as a capture's are (a file's text, for
        search). 201 with the page, appended_on (the revision the embeds went onto;
        null with no image) and added (each file's sha256, mime, filename and
        download_url); a retry with the same id returns 200, appended_on null.
        Mirrored as /mcp/pages/{key}/captures (mcp_files, SCRAP_MCP_UPLOAD), where
        it is Claude's: author claude, source mcp (is:claude-edited)."""
        if int(request.headers.get("content-length") or 0) > limit:
            raise TooLargeError(too_large(limit))
        if not request.headers.get("content-type", "").startswith(
            "multipart/form-data"
        ):
            raise InvalidError("expected multipart/form-data")
        who, claude = author(request), by_mcp(request)
        async with request.form() as form:  # closes the spooled uploads
            data = {k: v for k, v in form.items() if isinstance(v, str)}
            files = [f for f in form.getlist("file") if isinstance(f, UploadFile)]
            page = await run_in_threadpool(save, key, data, files, who, claude)
        response.status_code = 201 if page.pop("created") else 200
        return page
