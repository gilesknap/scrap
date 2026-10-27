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

from .store import InvalidError, Store, TooLargeError
from .store.constants import SOURCES, ULID
from .store.photos import addable
from .uploads import author, mimes, put_files, too_large

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
        key: str, form: dict[str, Any], uploads: list[UploadFile], who: str
    ) -> dict[str, Any]:
        cid, source, created = fields(form)  # before writing any file
        if not uploads:
            raise InvalidError("no photo to add")
        types = mimes(uploads)
        if not all(addable(t) for t in types):
            raise NotImageError
        blobs = put_files(store, uploads, types)
        page, created_now = store.add_photos(key, cid, blobs, who, source, created)
        wake()
        return {**page, "created": created_now}

    @app.post("/api/pages/{key}/captures", status_code=201)
    async def add_photos(key: str, request: Request, response: Response) -> Any:
        """Add photos or files to a page: multipart id (a ULID, the retry key) and file
        parts, images, PDFs and text or Markdown files only (415 otherwise; an untyped
        part is typed by its name). Each new image's embed goes to the end of its text
        as it is now, as a new revision; a file is listed below the text, not put in
        it. They are read as a capture's are (a file's text, for search). 201 with the
        page and appended_on (the revision the embeds went onto; null with no image); a
        retry with the same id returns 200, appended_on null."""
        if int(request.headers.get("content-length") or 0) > limit:
            raise TooLargeError(too_large(limit))
        if not request.headers.get("content-type", "").startswith(
            "multipart/form-data"
        ):
            raise InvalidError("expected multipart/form-data")
        who = author(request)
        async with request.form() as form:  # closes the spooled uploads
            data = {k: v for k, v in form.items() if isinstance(v, str)}
            files = [f for f in form.getlist("file") if isinstance(f, UploadFile)]
            page = await run_in_threadpool(save, key, data, files, who)
        response.status_code = 201 if page.pop("created") else 200
        return page
