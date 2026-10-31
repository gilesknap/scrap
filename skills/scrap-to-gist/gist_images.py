#!/usr/bin/env python3
"""Download a scrap page's images, for its gist.

Usage: gist_images.py PAGE.md [--out DIR] [--map FILE] [--server NAME]
                      [--headers-helper PATH [--scrap-host URL]] [--max-mb N]

PAGE.md is the page's body_markdown, as step 1 of SKILL.md saves it. For each of
scrap's files the body shows or links (/api/blobs/<sha>, .../preview?size=N,
...?download=1; outside code), this fetches its preview,
/mcp/blobs/<sha>/preview?size=2048 (scrap 1.2.0 or later), saves it as
z-img-<n>-<short sha>.<ext> in DIR (the extension from its content type) and writes
FILE (default DIR/images.json): each reference, as the body has it, -> the file name.
Give that to scrap_to_gist.py --images.

Only previews are fetched, never an original: a preview is what scrap shows, at most
2048 pixels a side, and has no EXIF (no GPS position); an SVG is its own preview. A
file with no preview (a PDF, an image scrap cannot decode) is not copied, and the
converter then warns about its reference. A file over --max-mb (default 5) is
reported; one over 4 times that is not saved.

Where, and with what headers: only the user's own scrap MCP server. Its address is
the url of the entry --server (default scrap) in the user's mcpServers in
~/.claude.json (or $CLAUDE_CONFIG_DIR/.claude.json), and its headers are that entry's
(the headersHelper, run as Claude Code runs it, and static headers with ${VAR}
expanded). --headers-helper PATH (or $SCRAP_HEADERS_HELPER) names a helper instead,
run as a program, with the address from --scrap-host (or $SCRAP_URL), which it then
needs. Every URL is built here from that address and a sha in the body, and checked to
be on it before it is fetched; plain HTTP only to loopback. The headers never follow a
redirect and are never printed or written. Every request says User-Agent:
scrap-to-gist/1 (Cloudflare refuses urllib's own, error 1010); a User-Agent in the
user's headers is dropped, so this one always wins.

Exit status: 0 done, 1 an image was not copied (other than a file with no preview),
2 no image was found on the server (older than 1.2.0, without /mcp/blobs). Only the
standard library is used.
"""

import argparse
import email.utils
import http.client
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# gist_convert.py is beside this script (also when it is loaded by path)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gist_convert import blob_refs  # noqa: E402

OLD = 2  # exit status: nothing found under /mcp/blobs (scrap before 1.2.0)
SIZE = 2048  # the preview scrap shows on a page
EXT = {  # a content type's extension, where mimetypes' choice is not the usual one
    "image/jpeg": "jpg",
    "image/svg+xml": "svg",
    "image/webp": "webp",
}
LOOPBACK = ("localhost", "127.0.0.1", "::1")
# Sent on every request, in place of any the user's headers give: Cloudflare in front
# of scrap answers urllib's own "Python-urllib/3.x" with 403, error code 1010
USER_AGENT = "scrap-to-gist/1"
CF_ERROR = re.compile(rb"error code: (\d{1,5})")  # a Cloudflare error page's body
PORTS = {"https": 443, "http": 80}


class FetchError(Exception):
    """A download or the headers failed: the message says why, with no secret."""


class NoPreviewError(FetchError):
    """The file has no preview (400: not an image scrap can decode)."""


class MissingError(FetchError):
    """404: no such file, or no /mcp/blobs (a server before 1.2.0)."""


# --- the server -----------------------------------------------------------------------


def origin(url: str) -> str:
    """url's origin, as scheme://host:port (lower case, the port written out): the
    only form compared. A URL with a user or password, or not http(s), is refused."""
    u = urlsplit(url.strip())
    if u.scheme.lower() not in PORTS or not u.hostname:
        raise FetchError(f"not an http(s) address: {url!r}")
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise FetchError(f"an address with a user or password is refused: {url!r}")
    try:
        port = u.port or PORTS[u.scheme.lower()]
    except ValueError:
        raise FetchError(f"a bad port in {url!r}") from None
    host = u.hostname.lower()
    return f"{u.scheme.lower()}://{f'[{host}]' if ':' in host else host}:{port}"


def trusted(url: str) -> str:
    """The origin of the scrap address url, which must be https unless loopback."""
    url = url.rstrip("/").removesuffix("/mcp")
    found = origin(url)
    host = found.split("://", 1)[1].rsplit(":", 1)[0].strip("[]")
    if found.startswith("http:") and host not in LOOPBACK:
        raise FetchError(f"refusing to send the MCP headers over plain HTTP: {url}")
    return found


def preview_url(base: str, sha: str) -> str:
    """The preview of sha on the server at base (an origin), checked to be there."""
    url = f"{base}/mcp/blobs/{sha}/preview?size={SIZE}"
    if not re.fullmatch("[0-9a-f]{64}", sha) or origin(url) != base:
        raise FetchError(f"refusing {url}: not on {base}")
    return url


# --- headers ------------------------------------------------------------------------


def user_servers() -> dict[str, Any]:
    """The user's own MCP servers: mcpServers at the top of ~/.claude.json (no
    project's, and never a .mcp.json, which a repository could hold)."""
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~")
    path = Path(home) / ".claude.json"
    try:
        conf = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    servers = conf.get("mcpServers") if isinstance(conf, dict) else None
    return servers if isinstance(servers, dict) else {}


def parse_headers(out: str) -> dict[str, str]:
    """A helper's output: a JSON object of strings. Never shown."""
    try:
        headers = json.loads(out)
    except ValueError:
        raise FetchError("the headers helper did not print a JSON object") from None
    if not isinstance(headers, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
    ):
        raise FetchError("the headers helper did not print a JSON object of strings")
    return headers


CONTROL = re.compile(r"[\x00-\x1f\x7f]")
TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def clean(headers: dict[str, str]) -> dict[str, str]:
    """headers with the spaces round each value stripped; a name that is not an HTTP
    token, or a value with a control character (a CR or LF) is refused, by name only:
    http.client would put the value in its error."""
    out = {}
    for k, v in headers.items():
        k, v = k.strip(), v.strip()
        if not TOKEN.fullmatch(k) or CONTROL.search(v):
            shown = k if TOKEN.fullmatch(k) else "(a bad name)"
            raise FetchError(
                f"the MCP header {shown} has a control character or is bad"
            )
        out[k] = v
    return out


def run_helper(cmd: str | list[str], name: str, url: str) -> dict[str, str]:
    """The headers a helper prints: cmd a shell command (an entry's headersHelper, as
    Claude Code runs it) or a program and its arguments. Nothing it prints is shown."""
    env = os.environ | {
        "CLAUDE_CODE_MCP_SERVER_NAME": name,
        "CLAUDE_CODE_MCP_SERVER_URL": url,
    }
    try:
        done = subprocess.run(
            cmd,
            shell=isinstance(cmd, str),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise FetchError("the headers helper took over 60 s") from None
    except OSError as e:
        raise FetchError(f"cannot run the headers helper: {e.strerror}") from None
    if done.returncode:
        raise FetchError(f"the headers helper failed (exit {done.returncode})")
    return parse_headers(done.stdout)


def server(
    name: str, helper: str | None, host: str | None
) -> tuple[str, dict[str, str], str]:
    """(the trusted origin, its headers, where they came from)."""
    if helper:
        if not host:
            raise FetchError(
                "--headers-helper needs the scrap address: --scrap-host or SCRAP_URL"
            )
        base = trusted(host)
        headers = clean(run_helper([helper], name, host))
        return base, headers, f"headers helper {helper}"
    e = user_servers().get(name)
    if not isinstance(e, dict) or not isinstance(e.get("url"), str):
        raise FetchError(
            f"no MCP server {name!r} with a url in the mcpServers of ~/.claude.json: "
            "pass --server NAME, or --headers-helper PATH with --scrap-host URL"
        )
    base = trusted(e["url"])
    headers: dict[str, str] = {}
    if isinstance(e.get("headers"), dict):  # Claude Code expands ${VAR} in these
        headers = {
            str(k): re.sub(
                r"\$\{(\w+)(?::-([^}]*))?\}",
                lambda m: os.environ.get(m[1], m[2] or ""),
                str(v),
            )
            for k, v in e["headers"].items()
        }
    source = f"the headers of MCP server {name!r}"
    if isinstance(e.get("headersHelper"), str):
        headers |= run_helper(e["headersHelper"], name, e["url"])
        source = f"the headersHelper of MCP server {name!r}"
    return base, clean(headers), source


def with_user_agent(headers: dict[str, str]) -> dict[str, str]:
    """headers (already clean) with any User-Agent, in any case, replaced by ours: one
    User-Agent, always the one Cloudflare lets through."""
    out = {k: v for k, v in headers.items() if k.lower() != "user-agent"}
    return out | {"User-Agent": USER_AGENT}


# --- downloading ----------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect (Cloudflare Access's login page, say) is an error: the headers must
    not follow it to another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FetchError(
            f"redirected (HTTP {code}): a login page? Check the MCP headers"
            f" (the service token)"
        )


# no proxy (http_proxy would get the headers, in clear to a loopback scrap), no redirect
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def retry_after(value: str | None) -> float:
    """Seconds to wait, from a Retry-After header (seconds or an HTTP date): 0 to 30."""
    try:
        wait = float(value or 5)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value or "")
            if when.tzinfo is None:  # "-0000": UTC
                when = when.replace(tzinfo=UTC)
            wait = (when - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError):
            wait = 5
    return max(0.0, min(wait, 30.0))


def refused_hint(e: urllib.error.HTTPError) -> str:
    """Why a 401 or 403 came: Cloudflare's own refusal (its body is just "error code:
    NNNN"; only that code is shown, never the body) or scrap's (the headers)."""
    try:
        body = e.read(4096) or b""
    except (OSError, http.client.HTTPException, ValueError):
        body = b""
    if m := CF_ERROR.search(body):
        code = m[1].decode()
        why = " (browser signature banned)" if code == "1010" else ""
        return (
            f" (Cloudflare blocked this client before it reached scrap: error code "
            f"{code}{why})"
        )
    return " (check the MCP headers)"


def fetch(url: str, base: str, headers: dict[str, str], cap: int) -> tuple[bytes, str]:
    """(bytes, content type) of url, which must be on base; a busy preview (503) is
    tried again. More than cap bytes is an error. Always GET: /mcp/blobs answers HEAD
    with 404, so do not "optimise" a check to HEAD."""
    if origin(url) != base:
        raise FetchError(f"refusing {url}: not on {base}")
    headers = with_user_agent(headers)
    for attempt in range(4):
        req = urllib.request.Request(url, headers=headers)
        try:
            with _opener.open(req, timeout=120) as r:
                data = bytearray()
                while chunk := r.read(65536):
                    data += chunk
                    if len(data) > cap:
                        raise FetchError(f"over {cap / 1e6:g} MB: not saved")
                length = r.headers.get("Content-Length")
                if length and length.isdigit() and int(length) != len(data):
                    raise FetchError(f"cut short reading {url}: not saved")
                return bytes(data), r.headers.get_content_type()
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < 3:
                time.sleep(retry_after(e.headers.get("Retry-After")))
                continue
            if e.code == 400:
                raise NoPreviewError(
                    "no preview: not an image scrap can show"
                ) from None
            if e.code == 404:
                raise MissingError(f"HTTP 404 for {url}") from None
            hint = refused_hint(e) if e.code in (401, 403) else ""
            raise FetchError(f"HTTP {e.code} for {url}{hint}") from None
        except urllib.error.URLError as e:
            raise FetchError(f"cannot reach {url}: {e.reason}") from None
        except (OSError, http.client.HTTPException) as e:  # a timeout, a dropped line
            raise FetchError(f"{type(e).__name__} reading {url}") from None
        except (ValueError, UnicodeError):  # a bad header: its error would show it
            raise FetchError(f"a header could not be sent to {url}") from None
    raise AssertionError("unreachable")


def extension(ctype: str) -> str:
    """A file's extension, from its content type."""
    ext = EXT.get(ctype) or (mimetypes.guess_extension(ctype) or "").lstrip(".")
    return re.sub(r"[^a-z0-9]", "", ext.lower()) or "bin"


def main() -> None:
    p = argparse.ArgumentParser(description="Download a scrap page's images.")
    p.add_argument("page", help="the page's body_markdown, saved as a file")
    p.add_argument("--out", default=".", help="folder for the images (default: .)")
    p.add_argument("--map", help="the mapping to write (default: OUT/images.json)")
    p.add_argument("--server", default="scrap", help="the MCP server's name (scrap)")
    p.add_argument(
        "--headers-helper",
        default=os.environ.get("SCRAP_HEADERS_HELPER"),
        help="a program printing the MCP headers as JSON (default: "
        "$SCRAP_HEADERS_HELPER); needs --scrap-host",
    )
    p.add_argument(
        "--scrap-host",
        default=os.environ.get("SCRAP_URL"),
        help="scrap's address, with --headers-helper (default: $SCRAP_URL)",
    )
    p.add_argument("--max-mb", type=float, default=5, help="report files over this")
    a = p.parse_args()

    body = Path(a.page).read_text(encoding="utf-8")
    refs = list(dict.fromkeys(blob_refs(body)))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = Path(a.map) if a.map else out / "images.json"
    mapping: dict[str, str] = {}
    base, headers = "", {}
    if refs:
        try:
            base, headers, source = server(a.server, a.headers_helper, a.scrap_host)
        except FetchError as e:
            sys.exit(str(e))
        print(f"server: {base}; headers: {source}")
    cap = int(a.max_mb * 4e6)
    saved: dict[str, str] = {}  # sha -> file
    failed, missing, skipped = [], [], []
    for ref in refs:
        sha = ref[len("/api/blobs/") :][:64]
        if sha in saved:
            mapping[ref] = saved[sha]
            continue
        try:
            url = preview_url(base, sha)
            data, ctype = fetch(url, base, headers, cap)
            if not ctype.startswith("image/"):
                raise FetchError(f"{url} is {ctype}, not an image")
        except NoPreviewError as e:
            skipped.append(ref)
            print(f"not copied: {ref}: {e}")
            continue
        except FetchError as e:
            (missing if isinstance(e, MissingError) else failed).append(ref)
            print(f"failed: {ref}: {e}", file=sys.stderr)
            continue
        name = f"z-img-{len(saved) + 1}-{sha[:8]}.{extension(ctype)}"
        (out / name).write_bytes(data)
        saved[sha] = mapping[ref] = name
        size = len(data) / 1e6
        print(f"{name}: {ctype}, {size:.2f} MB, for {ref}")
        if size > a.max_mb:
            print(
                f"warning: {name} is {size:.1f} MB, over {a.max_mb:g} MB: shrink it "
                "or leave it out",
                file=sys.stderr,
            )
    dest.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    print(f"{len(mapping)} of {len(refs)} references mapped in {dest}")
    if missing and not saved and not failed:
        print(
            "No image was found under /mcp/blobs: the server may be older than "
            "scrap 1.2.0. Leave the images out of the gist.",
            file=sys.stderr,
        )
        sys.exit(OLD)
    sys.exit(1 if failed or missing else 0)


if __name__ == "__main__":
    main()
