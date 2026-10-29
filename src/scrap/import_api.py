"""The HTTP routes for importing Markdown (Settings > Import Markdown): what an import
would cost, and the import of a zip (importer/). Registered by app.create_app
(add_routes). An archive over the upload limit goes through `scrap import` instead."""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from . import importer, ingest
from .store import InvalidError, Store, TooLargeError, enrich_on
from .uploads import author, too_large

UNPACKED = 20  # a zip may hold this many times the upload limit, unpacked
DETAILS = 20  # issues of each kind listed in the reply (all are counted)
YES = ("1", "true", "on", "yes")


def add_routes(
    app: FastAPI, store: Store, wake: Callable[[], None], limit: int
) -> None:
    @app.get("/api/import")
    def import_terms() -> dict[str, Any]:
        """What Settings shows before an import: the largest zip it takes, whether
        Claude can tag and summarise text pages (enrich) and read photos here, and
        roughly what each costs, in dollars (importer.cost)."""
        return {
            "max_upload_bytes": limit,
            "enrich": enrich_on(),
            "photos": ingest.enabled(),
            "page_usd": round(importer.per_page(), 4),
            "photo_usd": round(importer.per_photo(), 4),
        }

    def save(upload: UploadFile, who: str, enrich: bool, photos: bool) -> dict:
        try:
            src = importer.source(upload.file, total=UNPACKED * limit)
        except importer.RefusedError as e:
            raise InvalidError(f"not imported: {e}") from None
        try:
            plan = importer.plan(src, store)
            done = importer.run(store, src, plan, who, enrich=enrich, photos=photos)
        except importer.RefusedError as e:
            raise InvalidError(f"import stopped: {e}") from None
        finally:
            src.close()
        if done.enrich or done.photos or done.files:
            wake()
        return {
            "new": done.new,
            "skipped": done.skipped,
            "enrich": done.enrich,
            "photos": done.photos,
            "files": done.files,
            "tag": plan.tag,
            "kinds": importer.summary(plan)["kinds"],
            "issues": {
                what: {"count": len(items), "items": items[:DETAILS]}
                for what, items in sorted(plan.issues.items())
            },
        }

    @app.post("/api/import")
    async def import_zip(request: Request) -> dict[str, Any]:
        """Import a zip of Markdown pages (a scrap export, an Obsidian vault):
        multipart file, and enrich and photos ("1" to queue the new text pages for
        Claude to tag and summarise, and their photos for Claude to read; both off
        by default). Every new page is tagged import/<date>; a page here already (by
        its id, else by its path and bytes) is skipped, never overwritten. Returns
        new, skipped, what was queued, the tag, the new pages by kind and the
        problems found (each kind counted, its first DETAILS listed). 413 over the
        upload limit (`scrap import` takes any size); 422 for a file that is not a
        zip, or one refused whole (a name that climbs out of it, too many files)."""
        if int(request.headers.get("content-length") or 0) > limit:
            raise TooLargeError(too_large(limit))
        if not request.headers.get("content-type", "").startswith(
            "multipart/form-data"
        ):
            raise InvalidError("expected multipart/form-data")
        who = author(request)
        async with request.form(max_files=1, max_fields=8) as form:
            upload = form.get("file")
            if not isinstance(upload, UploadFile):
                raise InvalidError("no zip file sent (file)")
            enrich = str(form.get("enrich") or "").lower() in YES
            photos = str(form.get("photos") or "").lower() in YES
            return await run_in_threadpool(save, upload, who, enrich, photos)
