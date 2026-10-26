"""The HTTP routes for capturing and editing pages: captures, the share target, the
recent list, a page, its edits, delete and undelete, and asking Claude to read it.
Registered by app.create_app (add_routes)."""

import re
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, BeforeValidator, Field, StrictBool, StrictInt
from starlette.datastructures import UploadFile

from . import enrich
from .api_models import EnrichOffError, Text
from .store import (
    MAX_FIELDS,
    MAX_TAGS,
    InvalidError,
    Store,
    TooLargeError,
    enrich_on,
    new_ulid,
)
from .uploads import author, mimes, put_files, too_large

SHARED_LINK = re.compile(r"(?:^|\s)(https?://\S+)$")


FIELD_NAME = Annotated[Text, Field(min_length=1, max_length=40)]
# A field's value: flat, as the importer stores them too (None in a PATCH drops it)
# Numbers a browser holds exactly: whole within +-2**53, others finite (1e400 is not)
FIELD_INT = Annotated[StrictInt, Field(ge=-(2**53), le=2**53)]


def _only_float(value: Any) -> Any:
    """Not an int: pydantic would take one past FIELD_INT's range as a float."""
    if not isinstance(value, float):
        raise ValueError("not a decimal number")
    return value


FIELD_FLOAT = Annotated[
    float, BeforeValidator(_only_float), Field(strict=True, allow_inf_nan=False)
]

FIELD = Annotated[Text, Field(max_length=200)] | StrictBool | FIELD_INT | FIELD_FLOAT


class PageEdit(BaseModel):
    base_rev: int | None = None  # needed with a title or body
    title: Text | None = None
    body: Text | None = None
    kind: Text | None = None  # one the user chose: fixed, ingest keeps it
    fields: (
        Annotated[dict[FIELD_NAME, FIELD | None], Field(max_length=MAX_FIELDS)] | None
    ) = None
    tags: Annotated[list[Text], Field(max_length=MAX_TAGS)] | None = None  # all of them
    # The tags the editor started from: Claude's added since are kept, not retired
    tags_shown: Annotated[list[Text], Field(max_length=MAX_TAGS)] | None = None
    # A todo's (null clears one): sent or not tells apart, see todo()
    due: Annotated[Text, Field(max_length=10)] | None = None  # YYYY-MM-DD
    priority: Annotated[Text, Field(max_length=10)] | None = None  # high, medium, low
    snoozed_until: Annotated[Text, Field(max_length=10)] | None = None  # YYYY-MM-DD

    def todo(self) -> dict[str, str | None]:
        """The due date and priority sent, null too (it clears one)."""
        return {
            k: getattr(self, k)
            for k in ("due", "priority", "snoozed_until")
            if k in self.model_fields_set
        }


def add_routes(app: FastAPI, store: Store, limit: int) -> None:
    def save(data: dict[str, Any], uploads: list[UploadFile], who: str):
        types = mimes(uploads)
        capture = store.prepare(data, types)  # before writing any file
        saved = store.capture(capture, put_files(store, uploads, types), who)
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
                data: dict[str, Any] = {
                    k: v for k, v in form.items() if isinstance(v, str)
                }
                data["tags"] = form.getlist("tags")  # one field per tag
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
        and/or the kind, fields, tags, and a todo's due date and priority."""
        if edit.base_rev is None and (edit.title, edit.body) != (None, None):
            raise InvalidError("base_rev is needed to change the title or body")
        who = author(request)
        return store.update_page(
            key, edit.base_rev, edit.title, edit.body, who, edit.kind, edit.fields,
            edit.tags, edit.todo(), tags_shown=edit.tags_shown,
        )  # fmt: skip

    @app.delete("/api/pages/{key}", status_code=204)
    def delete(key: str) -> None:
        """Move a page to the trash."""
        store.delete_page(key)

    @app.post("/api/pages/{key}/undelete")
    def undelete(key: str) -> dict[str, Any]:
        """Bring a page back from the trash."""
        store.delete_page(key, undo=True)
        return store.page(key)

    @app.post("/api/pages/{key}/enrich")
    def enrich_page(key: str) -> dict[str, Any]:
        """Ask Claude to read a page now (tags, summary, related pages; a link is
        fetched): queued, and the page returned as it is; 409 while Claude is off."""
        if not enrich_on():
            raise EnrichOffError
        page = enrich.ask(store, key)
        if app.state.worker:
            app.state.worker.wake()
        return page
