"""The HTTP route that adds photos to a page that exists (#260): the page editor's Add
photo. Registered by app.create_app (add_routes)."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from .store import InvalidError, Store, TooLargeError
from .store.constants import SOURCES, ULID
from .uploads import author, mimes, put_files, too_large


class NotImageError(Exception):
    """Only images can be added to a page; other files need a capture of their own."""


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
        return JSONResponse({"detail": NotImageError.__doc__}, 415)

    app.add_exception_handler(NotImageError, refused)

    def save(
        key: str, form: dict[str, Any], uploads: list[UploadFile], who: str
    ) -> dict[str, Any]:
        cid, source, created = fields(form)  # before writing any file
        if not uploads:
            raise InvalidError("no photo to add")
        types = mimes(uploads)
        if not all(t.startswith("image/") for t in types):
            raise NotImageError
        blobs = put_files(store, uploads, types)
        page, created_now = store.add_photos(key, cid, blobs, who, source, created)
        wake()
        return {**page, "created": created_now}

    @app.post("/api/pages/{key}/captures", status_code=201)
    async def add_photos(key: str, request: Request, response: Response) -> Any:
        """Add photos to a page: multipart id (a ULID, the retry key) and file parts,
        images only (415 otherwise). Each new image's embed goes to the end of its
        text as it is now, as a new revision, and its photos are read as a capture's
        are. 201 with the page and appended_on (the revision the embeds went onto); a
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
