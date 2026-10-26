"""Serving the built PWA: index.html on every app route, with the version and the
public origins filled in, and its files. Registered by app.create_app (add_routes),
after every other route: its mount is a catch-all."""

import logging
import os
from pathlib import Path
from xml.sax.saxutils import quoteattr

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .public import public_origins

STATIC = Path(__file__).parent / "static"  # the built PWA (npm --prefix web run build)

# Served index.html
APP_ROUTES = (
    "/",
    "/recent",
    "/search",
    "/tags",
    "/todos",
    "/topics",
    "/health",
    "/p/{key}",
)
NOT_BUILT = (
    "The scrap PWA is not built. Run: npm --prefix web ci && npm --prefix web run build"
    "\n(the API under /api works without it)\n"
)


VERSION_SLOT = '<small id="ver" aria-hidden="true"></small>'  # in the PWA's index.html
# Also there: the origins of $SCRAP_PUBLIC_URL, so the PWA opens a page's full address
# on any of them in place (render.ts own). In the shell the service worker keeps, so
# offline too; a changed setting reaches an installed PWA with its next update.
ORIGINS_SLOT = '<meta name="scrap-origins" content="" />'


class Shell(StaticFiles):
    """The built PWA. Hashed assets are cached for good; the rest is revalidated, so
    a new build's service worker and manifest are noticed."""

    def file_response(self, full_path, *args, **kwargs):
        response = super().file_response(full_path, *args, **kwargs)
        immutable = "/assets/" in str(full_path)
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if immutable else "no-cache"
        )
        return response


def add_routes(app: FastAPI) -> None:
    # $SCRAP_WEB_DIR serves a PWA build from elsewhere, e.g. one being tried out live
    static = Path(os.environ.get("SCRAP_WEB_DIR") or STATIC)
    index = static / "index.html"
    if not index.is_file():
        logging.getLogger(__name__).warning(NOT_BUILT.splitlines()[0])

    def shell() -> Response:
        """The PWA: every app route loads index.html and routes in the browser."""
        if not index.is_file():
            return PlainTextResponse(NOT_BUILT, 503)
        slot = VERSION_SLOT.replace("></", f">v{__version__.split('+')[0]}</")
        origins = ORIGINS_SLOT.replace('""', quoteattr(" ".join(public_origins())))
        html = (
            index.read_text(encoding="utf-8")
            .replace(VERSION_SLOT, slot)
            .replace(ORIGINS_SLOT, origins)
        )
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    for route in APP_ROUTES:
        app.get(route, include_in_schema=False)(shell)
    if static.is_dir():
        app.mount("/", Shell(directory=static), name="static")
