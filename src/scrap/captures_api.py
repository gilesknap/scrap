"""The HTTP routes for a capture's photos and files: sending them to Claude again
(reprocess; a file is read again, locally), an image's guidance for its next reading
(#538), a PDF's read text, and a photo's drawing:
the current one, its versions, saving a scene from the editor and restoring
an old version. Registered by app.create_app (add_routes)."""

import json
import logging
from typing import Annotated, Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import drawing, ingest
from .api_models import Restore, Text
from .store import guidance as image_guidance
from .store import SURROGATE, InvalidError, NotFoundError, Store, TooLargeError
from .uploads import author, too_large

SCENE_REQUEST = 8 * 2**20  # a 5 MB scene, plus the files map it may carry (dropped)
FILE_TEXT = 20_000  # characters of a PDF's text the page view shows (search has it all)


WARNED: set[int] = set()  # the unencodable rows already logged


class Drawing(JSONResponse):
    """A drawing as JSON. A stored row that cannot be encoded (rows made before the
    sanitiser refused lone surrogates) is served with them replaced, and logged once,
    rather than failing every request for it."""

    def render(self, content: Any) -> bytes:
        try:
            return super().render(content)
        except UnicodeEncodeError:
            text = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
            seen = hash(text)
            if seen not in WARNED:  # once per row, not on every request for it
                if len(WARNED) >= 1000:
                    WARNED.clear()
                WARNED.add(seen)
                logging.getLogger(__name__).warning(
                    "drawing with unencodable text served"
                )
            return SURROGATE.sub("\ufffd", text).encode()


class Reprocess(BaseModel):
    photo: Text | None = None  # one photo's sha256; default all of the capture's
    replace_human: bool = False  # the user confirmed replacing their own drawing


class Guidance(BaseModel):
    # The owner's note for the image's next reading; empty or null: none
    guidance: Annotated[Text, Field(max_length=image_guidance.MAX_GUIDANCE)] | None = None


def photo(cid: str, sha: str) -> tuple[str, str]:
    """A photo's (capture id, sha256) as stored: upper and lower case."""
    return cid.upper(), sha.lower()


def add_routes(app: FastAPI, store: Store) -> None:
    @app.post("/api/captures/{cid}/reprocess")
    def reprocess(cid: str, ask: Reprocess) -> dict[str, int]:
        """Send a capture's photos (or one) to Claude again, or retry a failed one; a
        PDF or text file (or one) is read again, for search."""
        added = ingest.reprocess(store, cid.upper(), ask.photo, ask.replace_human)
        if app.state.worker:
            app.state.worker.wake()
        return added

    @app.put("/api/captures/{cid}/photos/{sha}/guidance")
    def photo_guidance(
        cid: str, sha: str, ask: Guidance, request: Request
    ) -> dict[str, str | None]:
        """Keep the owner's guidance for an image's next reading (empty or null:
        none): {guidance}. It queues nothing: Regenerate (reprocess) does, and sends
        it with the image. 404 for a capture or file not there, 422 for a file that
        is not an image Claude reads."""
        return ingest.set_guidance(store, *photo(cid, sha), ask.guidance, author(request))

    @app.get("/api/captures/{cid}/files/{sha}/text")
    def file_text(cid: str, sha: str) -> dict[str, Any]:
        """The text scrap read from a capture's PDF, for search (no model): {text,
        truncated}, its first FILE_TEXT characters; text null if none was read (a scan,
        not read yet, or failed). 404 for a file that is not a PDF of that capture, or a
        capture whose page is in the trash. The page view's file card, folded until
        opened: a text file's own link opens its text."""
        cid, sha = photo(cid, sha)
        with store.connect() as conn:
            found = conn.execute(
                "SELECT 1 FROM capture_blob cb JOIN capture c ON c.id = cb.capture_id"
                " JOIN page p ON p.id = c.page_id JOIN blob b ON b.sha256 = cb.sha256"
                " WHERE cb.capture_id = ? AND cb.sha256 = ? AND p.deleted_at IS NULL"
                " AND lower(trim(substr(b.mime, 1, instr(b.mime || ';', ';') - 1)))"
                " = 'application/pdf'",
                (cid, sha),
            ).fetchone()
        if found is None:
            raise NotFoundError(f"{cid}/{sha}")
        text, cut = store.file_text(cid, sha, FILE_TEXT)
        return {"text": text, "truncated": cut}

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
