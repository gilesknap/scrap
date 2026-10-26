"""The app's ASGI middleware: the request body limit and gzip for text."""

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .store import TooLargeError
from .uploads import too_large


class BodyLimit:
    """Raise TooLargeError while a request body is read, once it passes limit bytes.

    Covers chunked bodies with no Content-Length; the route turns it into a 413.
    """

    def __init__(self, app: ASGIApp, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b""))
            if seen > self.limit:
                raise TooLargeError(too_large(self.limit))
            return message

        await self.app(scope, counted, send)


class TextGzip:
    """Gzip what compresses: the PWA's scripts, styles and pages, and the API's JSON
    (a drawing is up to 5 MB of it). Not files (blobs, previews, downloads: photos and
    zips are compressed already, and they take range requests), nor fonts or images
    (excluded by type), nor any range request."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1024, compresslevel=6)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        files = path.startswith("/api/blobs/") or path.endswith("/download")
        ranged = any(k == b"range" for k, _ in scope.get("headers", ()))
        if scope["type"] != "http" or files or ranged:
            await self.app(scope, receive, send)
        else:
            await self.gzip(scope, receive, send)
