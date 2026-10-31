"""Downloads for MCP clients (#479): read-only GETs of files, drawings and page
downloads under /mcp/..., beside the PWA's /api/... ones; and, with SCRAP_MCP_UPLOAD
on, the one upload (#480, WRITES): adding files to a page. Registered by
app.create_app (add_routes), after the routes it mirrors.

Behind Cloudflare Access only /mcp takes the service token, and BearerAuth guards
/mcp and everything under it, so a machine client reaches these with the same two
headers as the MCP endpoint, while the browser's /api paths are left as they are
(ADR 0041). Each mirror is the /api route's own handler: one behaviour, two paths.
A write is a step up from a download (ADR 0042), so WRITES is its own list, served
only with SCRAP_MCP_UPLOAD on; its handler makes what comes by /mcp Claude's
(uploads.by_mcp).
"""

from fastapi import FastAPI, Response
from fastapi.routing import APIRoute

from . import drawing
from .backup import _drawing_name, file_name
from .blobs_api import BLOB_HEADERS, attachment
from .captures_api import photo
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
WRITES = (  # the /api POSTs a machine client may make, with SCRAP_MCP_UPLOAD on
    "/api/pages/{key}/captures",
)


def mirror(path: str) -> str:
    """The /mcp path of a mirrored /api one."""
    return PREFIX + path.removeprefix("/api")


def add_writes(app: FastAPI) -> None:
    """Mirror WRITES under /mcp, each the /api POST's own handler and status."""
    found = {
        r.path: r
        for r in app.router.routes
        if isinstance(r, APIRoute) and r.path in WRITES and "POST" in (r.methods or ())
    }
    if missing := set(WRITES) - set(found):  # a renamed route must not drop out
        raise RuntimeError(f"mcp_files: no POST route {sorted(missing)}")
    for path in WRITES:
        route = found[path]
        if route.dependencies:  # not copied: an auth dependency must not drop out
            raise RuntimeError(f"mcp_files: {path} has dependencies")
        app.add_api_route(
            mirror(path), route.endpoint, methods=["POST"],
            status_code=route.status_code, response_model=route.response_model,
            response_class=route.response_class, name=f"mcp_{route.name}",
            include_in_schema=False,
        )  # fmt: skip


def add_routes(app: FastAPI, store: Store, upload: bool = False) -> None:
    if upload:
        add_writes(app)
    found = {
        r.path: r
        for r in app.router.routes
        if isinstance(r, APIRoute) and r.path in MIRRORED and "GET" in (r.methods or ())
    }
    if missing := set(MIRRORED) - set(found):  # a renamed route must not drop out
        raise RuntimeError(f"mcp_files: no GET route {sorted(missing)}")
    for path in MIRRORED:
        route = found[path]
        if route.dependencies or route.status_code is not None:
            # not copied below: a route-level auth dependency must not drop out
            raise RuntimeError(f"mcp_files: {path} has dependencies or a status code")
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
        cid, sha = photo(cid, sha)
        current = drawing.current(store, cid, sha)
        file = file_name(store.blob_name(sha), sha, "")
        name = _drawing_name(file.rpartition(".")[0] or file, set())  # as backup's
        return Response(
            drawing.excalidraw_file(current["data"]),
            media_type="application/vnd.excalidraw+json",
            headers={"Content-Disposition": attachment(name),
                     "X-Content-Type-Options": BLOB_HEADERS["X-Content-Type-Options"],
                     "Cache-Control": "no-store"},
        )  # fmt: skip
