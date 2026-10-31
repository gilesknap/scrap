"""skills/scrap-to-gist/gist_images.py: download a scrap page's images for its gist.

Against a local HTTP server standing in for scrap's /mcp downloads, with a fake
headers helper; the script is installed on its own, so it is run and loaded by path."""

import importlib.util
import json
import subprocess
import sys
import threading
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "skills" / "scrap-to-gist" / "gist_images.py"
_spec = importlib.util.spec_from_file_location("gist_images", SCRIPT)
assert _spec and _spec.loader
gi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gi)

SECRET = "s3cr3t-token-value"
JPEG, PNG, SVG, PDF, FAIL, BIG, BUSY, LOOP, GONE = (c * 64 for c in "abcdef012")
PREVIEWS = {  # sha -> (content type, bytes) of its preview
    JPEG: ("image/jpeg", b"\xff\xd8 jpeg preview"),
    PNG: ("image/jpeg", b"\xff\xd8 png's preview"),  # every raster preview is a JPEG
    SVG: ("image/svg+xml", b"<svg/>"),  # an SVG is its own preview (#480)
    BIG: ("image/jpeg", b"x" * 50_000),
    BUSY: ("image/jpeg", b"\xff\xd8 busy"),
}


class Scrap(BaseHTTPRequestHandler):
    seen: list[tuple[str, dict[str, str]]] = []
    busy = 0

    def log_message(self, format, *args):  # quiet
        pass

    def do_GET(self):
        Scrap.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
        path, _, query = self.path.partition("?")
        parts = path.split("/")  # "", "mcp", "blobs", sha[, "preview"]
        sha = parts[3] if len(parts) > 3 else ""
        if sha == LOOP:
            self.send_response(302)
            self.send_header("Location", "https://login.example/")
            self.end_headers()
            return
        if parts[-1] != "preview":  # an original: has EXIF, must never be fetched
            return self.reply("image/jpeg", b"\xff\xd8 ORIGINAL with GPS")
        if sha == BUSY and not Scrap.busy:
            Scrap.busy += 1
            # an HTTP date in the past: try again at once
            return self.reply("text/plain", b"busy", 503, {"Retry-After": formatdate()})
        if sha in PREVIEWS and query == "size=2048":
            return self.reply(*PREVIEWS[sha])
        if sha == PDF:
            return self.reply("application/json", b'{"detail":"not an image"}', 400)
        if sha == FAIL:
            return self.reply("text/plain", b"oops", 500)
        self.reply("text/plain", b"no", 404)

    def reply(self, ctype, data, code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)


def serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Scrap)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def base():
    server = serve()
    Scrap.seen, Scrap.busy = [], 0
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def helper(folder: Path) -> Path:
    """A headers helper printing secrets, as the documented one does (in a folder
    with a space: it is run as a path, not split by a shell)."""
    folder.mkdir(exist_ok=True)
    script = folder / "headers.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'printf \'{{"Authorization":"Bearer {SECRET}",'
        f'"CF-Access-Client-Secret":"cf-{SECRET}"}}\\n\'\n'
    )
    script.chmod(0o700)
    return script


def run(tmp_path: Path, body: str, *args: str, **env: str):
    (tmp_path / "page.md").write_text(body)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "page.md", "--out", "img", *args],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)} | env,
    )


def with_helper(tmp_path: Path, body: str, base: str, *args: str):
    h = helper(tmp_path / "my dir")
    return run(tmp_path, body, "--headers-helper", str(h), *args, SCRAP_URL=base)


def mapping(tmp_path: Path) -> dict[str, str]:
    return json.loads((tmp_path / "img" / "images.json").read_text())


def leaked(tmp_path: Path, done) -> bool:
    """Whether a secret is in the output or in any file written."""
    files = [p.read_bytes() for p in (tmp_path / "img").rglob("*") if p.is_file()]
    return SECRET in done.stdout + done.stderr or any(
        SECRET.encode() in b for b in files
    )


def paths() -> list[str]:
    return [p for p, _ in Scrap.seen]


BODY = (
    f"Photo:\n\n![](/api/blobs/{JPEG}/preview?size=2048)\n\n"
    f"Again ![x](/api/blobs/{JPEG}/preview?size=2048) and small "
    f"![](/api/blobs/{JPEG}/preview?size=480)\n\n"
    f"![](/api/blobs/{PNG})\n\n![d](/api/blobs/{SVG}/preview?size=2048)\n\n"
    f"[photo file](/api/blobs/{PNG}?download=1)\n\n"
    f"[paper](/api/blobs/{PDF})\n\n`![](/api/blobs/{GONE}/preview?size=2048)`\n"
    f"![](http://127.0.0.1:1/api/blobs/{GONE})\n"
)


def test_it_downloads_previews_only_with_the_helper_headers(tmp_path, base):
    done = with_helper(tmp_path, BODY, base)
    assert done.returncode == 0, done.stderr
    j, p, s = (f"z-img-{n}-{sha[:8]}" for n, sha in ((1, JPEG), (2, PNG), (3, SVG)))
    assert mapping(tmp_path) == {
        f"/api/blobs/{JPEG}/preview?size=2048": f"{j}.jpg",
        f"/api/blobs/{JPEG}/preview?size=480": f"{j}.jpg",
        f"/api/blobs/{PNG}": f"{p}.jpg",  # the preview, a JPEG: the extension says so
        f"/api/blobs/{SVG}/preview?size=2048": f"{s}.svg",
        f"/api/blobs/{PNG}?download=1": f"{p}.jpg",
    }
    img = tmp_path / "img"
    assert (img / f"{j}.jpg").read_bytes() == b"\xff\xd8 jpeg preview"
    assert (img / f"{s}.svg").read_bytes() == b"<svg/>"
    # only previews, each once, never an original (it has EXIF); not the code span's
    # nor another host's
    want = [f"/mcp/blobs/{sha}/preview?size=2048" for sha in (JPEG, PNG, SVG, PDF)]
    assert paths() == want
    # the headers went with every request, and were never shown or written
    for _, sent in Scrap.seen:
        assert sent["authorization"] == f"Bearer {SECRET}"
        assert sent["cf-access-client-secret"] == f"cf-{SECRET}"
    assert not leaked(tmp_path, done)
    assert f"not copied: /api/blobs/{PDF}" in done.stdout  # no preview: a PDF


def test_it_finds_the_server_in_claude_json(tmp_path, base):
    conf = {
        "mcpServers": {
            "scrap": {"type": "http", "url": "https://elsewhere.example/mcp"},
            "my-scrap": {
                "type": "http",
                "url": f"{base}/mcp",
                "headers": {"X-Static": "${STATIC_VAR}"},
                "headersHelper": str(helper(tmp_path / "h")),
            },
        }
    }
    (tmp_path / ".claude.json").write_text(json.dumps(conf))
    body = f"![](/api/blobs/{JPEG}/preview?size=2048)"
    done = run(tmp_path, body, "--server", "my-scrap", STATIC_VAR=f"v-{SECRET}")
    assert done.returncode == 0, done.stderr
    assert "headersHelper of MCP server 'my-scrap'" in done.stdout
    sent = Scrap.seen[0][1]
    assert sent["authorization"] == f"Bearer {SECRET}"
    assert sent["x-static"] == f"v-{SECRET}"
    assert not leaked(tmp_path, done)


def test_only_the_named_entry_of_the_user_is_used(tmp_path, base):
    """No fallback to another entry or host, no project's entry, and never a
    .mcp.json (a repository could hold one): its helper is not run."""
    pwned = tmp_path / "PWNED"
    evil = {
        "type": "http",
        "url": f"{base}/mcp",
        "headersHelper": f"touch {pwned}; echo '{{}}'",
    }
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"scrap": evil}}))
    conf = {
        "mcpServers": {"other": evil},
        "projects": {str(tmp_path): {"mcpServers": {"scrap": evil}}},
    }
    (tmp_path / ".claude.json").write_text(json.dumps(conf))
    done = run(tmp_path, f"![](/api/blobs/{JPEG})")
    assert done.returncode != 0
    assert "no MCP server 'scrap'" in done.stderr
    assert not pwned.exists()
    assert not Scrap.seen


def test_a_helper_needs_the_scrap_address(tmp_path, base):
    h = helper(tmp_path / "h")
    done = run(tmp_path, f"![](/api/blobs/{JPEG})", SCRAP_HEADERS_HELPER=str(h))
    assert done.returncode != 0
    assert "needs the scrap address" in done.stderr
    assert not Scrap.seen
    done = run(tmp_path, "no images here", SCRAP_HEADERS_HELPER=str(h))
    assert done.returncode == 0, done.stderr
    assert mapping(tmp_path) == {}


def test_the_env_names_the_helper(tmp_path, base):
    h = helper(tmp_path / "my dir")
    body = f"![](/api/blobs/{JPEG})"
    done = run(tmp_path, body, SCRAP_HEADERS_HELPER=str(h), SCRAP_URL=base + "/mcp")
    assert done.returncode == 0, done.stderr
    assert Scrap.seen[0][1]["authorization"] == f"Bearer {SECRET}"


@pytest.mark.parametrize(
    "url, want",
    [
        ("https://Scrap.Example.com/mcp", "https://scrap.example.com:443"),
        ("https://scrap.example.com:443/", "https://scrap.example.com:443"),
        ("http://127.0.0.1:8000/mcp", "http://127.0.0.1:8000"),
        ("http://[::1]:8000", "http://[::1]:8000"),
    ],
)
def test_the_trusted_origin(url, want):
    assert gi.trusted(url) == want


@pytest.mark.parametrize(
    "url",
    [
        "https://scrap.example.com@evil.com/mcp",  # userinfo: the host is evil.com
        "https://user:pw@scrap.example.com/mcp",
        "http://scrap.example.com/mcp",  # plain HTTP off loopback
        "ftp://scrap.example.com/",
        "https://scrap.example.com:99999/",
    ],
)
def test_tricky_addresses_are_refused(url):
    with pytest.raises(gi.FetchError):
        gi.trusted(url)


def test_a_url_on_another_origin_is_refused():
    base = gi.trusted("https://scrap.example.com/mcp")
    assert gi.preview_url(base, JPEG) == (
        f"https://scrap.example.com:443/mcp/blobs/{JPEG}/preview?size=2048"
    )
    for url in (
        f"https://evil.com/mcp/blobs/{JPEG}/preview?size=2048",
        f"https://scrap.example.com:8443/mcp/blobs/{JPEG}/preview?size=2048",
        f"http://scrap.example.com/mcp/blobs/{JPEG}/preview?size=2048",
    ):
        with pytest.raises(gi.FetchError, match="not on"):
            gi.fetch(url, base, {"Authorization": "x"}, 10)
    with pytest.raises(gi.FetchError):
        gi.preview_url(base, "@evil.com/x")


def test_plain_http_off_loopback_is_refused(tmp_path):
    done = run(
        tmp_path,
        f"![](/api/blobs/{JPEG})",
        "--headers-helper",
        str(helper(tmp_path / "h")),
        "--scrap-host",
        "http://scrap.example",
    )
    assert done.returncode != 0
    assert "plain HTTP" in done.stderr


def test_a_failed_preview_does_not_fall_back(tmp_path, base):
    done = with_helper(tmp_path, f"![](/api/blobs/{FAIL})", base)
    assert done.returncode == 1
    assert "HTTP 500" in done.stderr
    assert paths() == [f"/mcp/blobs/{FAIL}/preview?size=2048"]  # no original
    assert mapping(tmp_path) == {}


def test_the_size_cap_aborts(tmp_path, base):
    body = f"![](/api/blobs/{BIG})\n\n![](/api/blobs/{JPEG})"
    done = with_helper(tmp_path, body, base, "--max-mb", "0.01")  # cap: 40 kB
    assert done.returncode == 1
    assert "over 0.04 MB: not saved" in done.stderr
    assert not list((tmp_path / "img").glob(f"*{BIG[:8]}*"))
    assert list(mapping(tmp_path)) == [f"/api/blobs/{JPEG}"]
    done = with_helper(tmp_path, f"![](/api/blobs/{BIG})", base, "--max-mb", "0.02")
    assert done.returncode == 0, done.stderr  # under the cap: saved, with a warning
    assert "over 0.02 MB" in done.stderr


def test_retry_after_as_an_http_date(tmp_path, base):
    done = with_helper(tmp_path, f"![](/api/blobs/{BUSY})", base)
    assert done.returncode == 0, done.stderr
    assert paths() == [f"/mcp/blobs/{BUSY}/preview?size=2048"] * 2
    assert gi.retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0
    assert gi.retry_after("7") == 7
    assert gi.retry_after("600") == 30
    assert gi.retry_after("soon") == 5
    assert gi.retry_after(formatdate()) <= 1  # "-0000", read as UTC


def test_a_dropped_line_is_reported_without_a_traceback(tmp_path):
    class Drop(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"short")  # then the line drops

    server = ThreadingHTTPServer(("127.0.0.1", 0), Drop)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        done = with_helper(tmp_path, f"![](/api/blobs/{JPEG})", url)
    finally:
        server.shutdown()
        server.server_close()
    assert done.returncode == 1
    assert "Traceback" not in done.stderr
    assert "cut short" in done.stderr
    assert mapping(tmp_path) == {}


def test_a_failing_helper_shows_nothing_it_printed(tmp_path, base):
    bad = tmp_path / "bad.sh"
    bad.write_text(f"#!/bin/sh\necho 'not json {SECRET}'\necho {SECRET} >&2\n")
    bad.chmod(0o700)
    body = f"![](/api/blobs/{JPEG})"
    done = run(tmp_path, body, "--headers-helper", str(bad), SCRAP_URL=base)
    assert done.returncode != 0
    assert "did not print a JSON object" in done.stderr
    assert SECRET not in done.stdout + done.stderr


def test_a_redirect_is_not_followed(tmp_path, base):
    """A login page's redirect: the headers must not follow it."""
    done = with_helper(tmp_path, f"![](/api/blobs/{LOOP})", base)
    assert done.returncode == 1
    assert "redirected (HTTP 302)" in done.stderr
    assert paths() == [f"/mcp/blobs/{LOOP}/preview?size=2048"]
    assert not leaked(tmp_path, done)


def test_an_old_server_has_no_mcp_blobs(tmp_path, base):
    done = with_helper(tmp_path, f"![](/api/blobs/{GONE})", base)
    assert done.returncode == 2
    assert "older than scrap 1.2.0" in done.stderr


def test_extensions():
    assert gi.extension("image/jpeg") == "jpg"
    assert gi.extension("image/png") == "png"
    assert gi.extension("image/svg+xml") == "svg"
    assert gi.extension("image/webp") == "webp"
    assert gi.extension("image/gif") == "gif"
    assert gi.extension("image/x-unknown") == "bin"


def test_a_header_with_a_control_character_is_refused_unshown(tmp_path, base):
    """A CR or LF in a value: http.client's error would print it."""
    conf = {"mcpServers": {"scrap": {"url": base, "headers": {"X-T": "${TOKEN}"}}}}
    (tmp_path / ".claude.json").write_text(json.dumps(conf))
    body = f"![](/api/blobs/{JPEG})"
    done = run(tmp_path, body, TOKEN=f"Bearer {SECRET}\r\nX-Evil: 1")
    assert done.returncode != 0
    assert "the MCP header X-T has a control character" in done.stderr
    assert SECRET not in done.stdout + done.stderr
    assert not Scrap.seen
    bad = tmp_path / "bad.sh"
    bad.write_text(
        f'#!/bin/sh\nprintf \'{{"Authorization":"Bearer {SECRET}\\\\nX: y"}}\'\n'
    )
    bad.chmod(0o700)
    done = run(tmp_path, body, "--headers-helper", str(bad), SCRAP_URL=base)
    assert done.returncode != 0
    assert "the MCP header Authorization has a control character" in done.stderr
    assert SECRET not in done.stdout + done.stderr
    assert not Scrap.seen
    # a value with spaces round it is stripped, not refused
    assert gi.clean({" A ": " b "}) == {"A": "b"}
    with pytest.raises(gi.FetchError, match="bad name"):
        gi.clean({"A\nB": "x"})


def test_a_proxy_is_never_used(tmp_path, base):
    """http_proxy would get the headers, in clear for a loopback scrap."""
    proxy = serve()
    seen_before = len(Scrap.seen)
    try:
        url = f"http://127.0.0.1:{proxy.server_port}"
        h = helper(tmp_path / "h")
        done = run(
            tmp_path,
            f"![](/api/blobs/{JPEG})",
            "--headers-helper",
            str(h),
            SCRAP_URL=base,
            http_proxy=url,
            HTTP_PROXY=url,
            no_proxy="",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
    assert done.returncode == 0, done.stderr
    # one request, straight to scrap (a proxy is sent the full URL as the path)
    assert [p for p, _ in Scrap.seen[seen_before:]] == [
        f"/mcp/blobs/{JPEG}/preview?size=2048"
    ]
