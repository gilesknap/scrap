"""Downloads for MCP clients (#479): read-only GETs of files, drawings and page
downloads under /mcp/..., beside the PWA's /api/... ones. Registered by
app.create_app (add_routes), after the routes it mirrors.

Behind Cloudflare Access only /mcp takes the service token, and BearerAuth guards
/mcp and everything under it, so a machine client reaches these with the same two
headers as the MCP endpoint, while the browser's /api paths are left as they are
(ADR 0041). Each mirror is the /api route's own handler: one behaviour, two paths.
"""

from fastapi import FastAPI, Response
from fastapi.routing import APIRoute

from . import drawing
from .backup import file_name
from .blobs_api import attachment
from .store import Store

PREFIX = "/mcp"
MIRRORED = (  # the /api GETs a machine client may make, and nothing else
    "/api/blobs/{sha}",
    "/api/blobs/{sha}/preview",
    "/api/blobs/{sha}/uses",
    "/api/pages/{key}/download",
    "/api/captures/{cid}/photos/{sha}/drawing",
    "/api/captures/{cid}/photos/{sha}/drawing/versions",
)


def mirror(path: str) -> str:
    """The /mcp path of a mirrored /api one."""
    return PREFIX + path.removeprefix("/api")


def add_routes(app: FastAPI, store: Store) -> None:
    found = {
        r.path: r
        for r in app.router.routes
        if isinstance(r, APIRoute) and r.path in MIRRORED and "GET" in (r.methods or ())
    }
    if missing := set(MIRRORED) - set(found):  # a renamed route must not drop out
        raise RuntimeError(f"mcp_files: no GET route {sorted(missing)}")
    for path in MIRRORED:
        route = found[path]
        app.add_api_route(
            mirror(path), route.endpoint, methods=["GET"],
            response_model=route.response_model, response_class=route.response_class,
            name=f"mcp_{route.name}", include_in_schema=False,
        )  # fmt: skip

    @app.get(
        mirror("/api/captures/{cid}/photos/{sha}/drawing.excalidraw"),
        include_in_schema=False,
    )
    def drawing_file(cid: str, sha: str) -> Response:
        """A photo's current drawing, whole, as an .excalidraw file (as a page's
        download has it); 404 if it has none."""
        current = drawing.current(store, cid.upper(), sha.lower())
        stem = file_name(store.blob_name(sha.lower()), sha.lower(), "")
        name = f"{stem.rpartition('.')[0] or stem}.excalidraw"
        return Response(
            drawing.excalidraw_file(current["data"]),
            media_type="application/vnd.excalidraw+json",
            headers={"Content-Disposition": attachment(name),
                     "Cache-Control": "no-store"},
        )  # fmt: skip
