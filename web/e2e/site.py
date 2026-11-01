"""The public site for the e2e tests: the receiver's www/ folder served as nginx
serves it (scrap-public/nginx.conf.template, docs/reference/public-site.md "nginx"),
so a spec can open what scrap published. Stdlib only; GET and HEAD.

    python web/e2e/site.py <site folder> <port>
"""

import mimetypes
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WWW = Path(sys.argv[1]) / "www"
SEGMENT = r"[A-Za-z0-9_][A-Za-z0-9._-]{0,99}"
# nginx's CSP by path (scrap-public/nginx.conf.template's map), first match wins
PAGE_CSP = (
    "default-src 'none'; img-src 'self' data:; style-src 'self';"
    " style-src-attr 'unsafe-inline'; font-src 'self'; script-src 'none';"
    " base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
HOME_CSP = (
    "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline';"
    " font-src 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self';"
    " base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
CSP = (
    (r"^/p/[a-z0-9-]+/file-[^/]*\.pdf$", "sandbox", re.IGNORECASE),
    (
        r"^/p/[a-z0-9-]+/(img|file)-",
        "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:;"
        " font-src data:",
        0,
    ),
    (r"^/[pt]/", PAGE_CSP, 0),
)
TYPES = {".wasm": "application/wasm", ".md": "text/markdown", ".mjs": "text/javascript"}


def where(path: str) -> Path | None:
    """The file nginx serves for a request path, None for its 404."""
    if path == "/":
        return WWW / "home" / "index.html"
    if path == "/tags":
        return WWW / "home" / "tags.html"
    if m := re.fullmatch(r"/(p/[a-z0-9-]{1,120}|t/[a-z0-9-]{1,80})/?", path):
        return WWW / m[1] / "index.html"
    if m := re.fullmatch(rf"/p/([a-z0-9-]{{1,120}})/({SEGMENT})", path):
        return WWW / "p" / m[1] / m[2]
    if m := re.fullmatch(rf"/(pagefind|assets)/((?:{SEGMENT}/){{0,3}}{SEGMENT})", path):
        return WWW / m[1] / m[2]
    return None


class Site(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/robots.txt":
            return self.send(200, b"User-agent: *\nDisallow: /\n", "text/plain")
        file = where(path)
        if file is None or not file.is_file():
            missing = WWW / "home" / "404.html"
            body = missing.read_bytes() if missing.is_file() else b"Not found"
            return self.send(404, body, "text/html")
        kind = TYPES.get(file.suffix) or mimetypes.guess_type(file.name)[0]
        self.send(200, file.read_bytes(), kind or "application/octet-stream")

    def do_HEAD(self) -> None:
        self.do_GET()

    def send(self, status: int, body: bytes, kind: str) -> None:
        path = self.path.split("?", 1)[0]
        csp = next((c for p, c, f in CSP if re.search(p, path, f)), HOME_CSP)
        if kind.startswith("text/"):
            kind += "; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        html = kind.startswith("text/html")
        self.send_header("Cache-Control", "no-cache" if html else "public, max-age=300")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2])), Site).serve_forever()
