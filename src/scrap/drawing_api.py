"""The HTTP routes for a photo's drawing: the current one, its versions, saving a
scene from the editor and restoring an old version. Registered by app.create_app
(add_routes)."""

import json
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import drawing
from .api_models import Restore
from .store import SURROGATE, InvalidError, Store, TooLargeError
from .uploads import author, too_large

SCENE_REQUEST = 8 * 2**20  # a 5 MB scene, plus the files map it may carry (dropped)


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


def add_routes(app: FastAPI, store: Store) -> None:
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
