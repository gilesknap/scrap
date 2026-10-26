"""What the routes that take uploads share: who sent a request, and storing its files.
Below pages_api, photos_api, captures_api, writeup_api and middleware, which import
it."""

import mimetypes
import os

from starlette.datastructures import UploadFile
from starlette.requests import Request

from .store import CLAUDE, Store

IDENTITY_HEADER = "Tailscale-User-Login"


def author(request: Request) -> str:
    # $SCRAP_IDENTITY_HEADER (default Tailscale-User-Login, set by Tailscale Serve);
    # tagged devices, and anything else without it, send none. Only this header is
    # trusted, so a proxy that sets another (X-Auth-Request-User) names it here. No
    # header makes a change Claude's: one naming claude (MCP's author) counts as none
    # (#153), and a web change's revision is source web whatever its author.
    name = os.environ.get("SCRAP_IDENTITY_HEADER", "").strip() or IDENTITY_HEADER
    who = request.headers.get(name, "")
    return "tagged" if not who or who.strip().lower() == CLAUDE else who


def too_large(limit: int) -> str:
    return f"over the {limit / 2**20:g} MB upload limit"


def mimes(uploads: list[UploadFile]) -> list[str]:
    """Each upload's type: as sent, else from its filename, else octet-stream."""
    found = []
    for upload in uploads:
        mime = upload.content_type
        if mime in (None, "", "application/octet-stream"):
            mime = mimetypes.guess_type(upload.filename or "")[0]
        found.append(mime or "application/octet-stream")
    return found


def put_files(
    store: Store, uploads: list[UploadFile], types: list[str]
) -> list[tuple[str, str, int, str | None]]:
    """Store the uploads in files/: (sha256, mime, size, filename) each."""
    blobs = []
    for upload, mime in zip(uploads, types, strict=True):
        sha, size = store.put_blob(upload.file)
        blobs.append((sha, mime, size, upload.filename or None))
    return blobs
