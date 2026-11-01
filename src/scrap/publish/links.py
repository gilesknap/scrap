"""Which ``href`` a published page may have (docs/reference/public-site.md, "Links
scrap accepts"): matched in full (re.fullmatch) after entity decoding, which the parser
has done. Anything not listed is refused: a relative /api/..., //..., /\\...,
javascript:, data: and the rest."""

import functools
import re
from urllib.parse import unquote, urlsplit

from ..public import origin, public_origins

__all__ = [
    "BLOB",
    "DIAGRAM",
    "DRAWING",
    "EXCALIDRAW",
    "ID",
    "PAGE",
    "TAG",
    "TAG_KEY",
    "classify",
    "normal_path",
    "own_hosts",
    "private_text",
    "scrub_code",
    "scrub_text",
]

BLOB = re.compile(r"scrap-blob:([0-9a-f]{64})")
# A drawing on the page (#520), by its id: the PWA uploads its SVG beside the HTML
DRAWING = re.compile(r"scrap-drawing:([1-9][0-9]{0,17})")
# Its "Open in Excalidraw" link, which scrap makes https://excalidraw.com/#url=<the
# SVG's address on the site> (rewrite.excalidraw_url)
EXCALIDRAW = re.compile(r"scrap-excalidraw:([1-9][0-9]{0,17})")
# A Mermaid diagram's image (#525), by its key and theme: the PWA uploads both SVGs
# beside the HTML, and the page's CSS shows the one for its theme
DIAGRAM = re.compile(r"scrap-diagram:([1-9][0-9]{0,2})-(light|dark)")
# encodeURIComponent's output: what the publish mode writes a tag as
TAG = re.compile(r"scrap-tag:([A-Za-z0-9%._~!*'()-]+)")
PAGE = re.compile(r"/p/([a-z0-9-]{1,120})")
TAG_KEY = re.compile(r"/t/([a-z0-9-]{1,80})")
ID = re.compile(r"[a-z0-9_-]{1,80}")  # render.ts's heading and footnote ids
FRAGMENT = re.compile(r"#[a-z0-9_-]{1,80}")
MAILTO = re.compile(r"mailto:[^\s\x00-\x1f\x7f]+", re.IGNORECASE)
ABSOLUTE = re.compile(r"https?://[^\s\x00-\x1f\x7f\\]+", re.IGNORECASE)
API = re.compile(r"/api(?:/|$)", re.IGNORECASE)
BLOBS = "/api/blobs/"  # a stored file's private address, in text


def _host(name: str) -> str:
    return name.lower().rstrip(".")


def own_hosts() -> frozenset[str]:
    """The hosts of scrap's own origins ($SCRAP_PUBLIC_URL), lower case, without a
    trailing dot."""
    hosts = set()
    for o in public_origins():
        hostname = urlsplit(o).hostname
        if hostname:
            hosts.add(_host(hostname))
    return frozenset(hosts)


# Zero-width characters dropped, and full-width or ideographic dots read as ".", before
# a text is matched (only to find a host: the text itself is not changed)
_FOLD = str.maketrans(
    {**dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad")),
     **dict.fromkeys(map(ord, "\u3002\uff0e\uff61"), ".")}
)  # fmt: skip


def _named(host: str) -> re.Pattern[str]:
    """host in lower-case text, only where it is not part of a longer name: no
    letter, digit, - or . before it, and no letter, digit or - after it, nor a .
    and then one (a full stop after it still counts)."""
    return re.compile(rf"(?<![a-z0-9.-]){re.escape(host)}(?![a-z0-9-]|\.[a-z0-9])")


def private_text(text: str) -> str | None:
    """What private address of scrap's a text holds, else None: /api/blobs/
    anywhere, or one of its own hosts as a name of its own (not inside a longer
    one), compared case-insensitively.

    Zero-width characters are ignored and full-width dots read as dots first, so
    neither hides a host.

    >>> private_text("see /API/Blobs/abc"), private_text("plain")
    ('/api/blobs/', None)
    """
    lower = text.translate(_FOLD).lower()
    if BLOBS in lower:
        return BLOBS
    for host in sorted(own_hosts()):
        if _named(host).search(lower):
            return host
    return None


PRIVATE_LINK = "a private link"  # what text says in place of a private address
# The rest of an address, as the publish mode (publish.ts privates) reads it: up to a
# space, not its last full stop, comma or bracket
_TAIL = r"[^\s<>\"]*[^\s<>\".,;:!?)]"
_CODE_TAIL = r"[^\s<>\"]*[^\s<>\".,;:!?)\]]"
_ZW = "[\u200b-\u200d\u2060\ufeff\u00ad]*"
_API = (
    rf"https?://[^\s/<>\"]*/api/(?:{_TAIL})?|(?<![\w.~/-])/api/(?:{_TAIL})?"
    rf"|/api/blobs/(?:{_TAIL})?"
)


def _privates(code: bool = False) -> re.Pattern[str]:
    """The pattern for scrap's hosts now (see _compiled)."""
    return _compiled(own_hosts(), code)


@functools.lru_cache(maxsize=8)
def _compiled(own: frozenset[str], code: bool) -> re.Pattern[str]:
    """Addresses of scrap's own (its hosts, with or without a scheme, port or path)
    and of /api/, as text: publish.ts's privates(), for text scrap writes itself (a
    drawing's, #520); in code (a diagram's, #525 and #529), only its hosts' and
    /api/blobs/ (what private_text finds): an /api/ path there is the text's own."""
    hosts = [
        _ZW.join("[.\u3002\uff0e\uff61]" if c == "." else re.escape(c) for c in host)
        for host in sorted(own)
    ]
    found = (
        rf"(?:(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://)?(?<![\w.-])(?:{'|'.join(hosts)})"
        rf"(?![\w-]|\.[\w-])\.?(?::\d+)?(?:[/?#]{_TAIL})?|"
        if hosts
        else ""
    )
    api = rf"/api/blobs/(?:{_TAIL})?" if code else _API
    if code:  # nor a square bracket: Mermaid's B[address] keeps its bracket
        found, api = (x.replace(_TAIL, _CODE_TAIL) for x in (found, api))
    return re.compile(found + api, re.IGNORECASE | re.ASCII)


def scrub_text(text: str) -> str:
    """text with every private address of scrap's (its own hosts, /api/...) as "a
    private link", by the same rules as the publish mode's for page text; a text
    that would still hold one (private_text) is "a private link" whole.

    >>> scrub_text("see /api/blobs/abc, then")
    'see a private link, then'
    """
    out = _privates().sub(PRIVATE_LINK, text)
    return PRIVATE_LINK if private_text(out) else out


def scrub_code(text: str) -> str:
    """text from code (a Mermaid diagram's, #525) with only scrap's own addresses
    (its hosts, /api/blobs/) as "a private link", as the publish mode does in a code
    block (#529): any other /api/ path stays as written.

    >>> scrub_code("API[/api/captures/] reads /api/blobs/abc")
    'API[/api/captures/] reads a private link'
    """
    out = _privates(code=True).sub(PRIVATE_LINK, text)
    return PRIVATE_LINK if private_text(out) else out


def _dot_segments(path: str) -> str:
    """RFC 3986's remove_dot_segments (5.2.4)."""
    out: list[str] = []
    while path:
        if path.startswith(("../", "./")):
            path = path.partition("/")[2]
        elif path.startswith("/./") or path == "/.":
            path = "/" + path[3:] if path != "/." else "/"
        elif path.startswith("/../") or path == "/..":
            path = "/" + path[4:] if path != "/.." else "/"
            if out:
                out.pop()
        elif path in (".", ".."):
            path = ""
        else:
            start = 1 if path.startswith("/") else 0
            end = path.find("/", start)
            end = len(path) if end < 0 else end
            out.append(path[:end])
            path = path[end:]
    return "".join(out)


def normal_path(path: str) -> str:
    """A URL's path as a server may read it: percent-decoded, repeated slashes as
    one, dot segments removed.

    >>> normal_path("/x/%2e%2e/api/x"), normal_path("//api/x"), normal_path("/a/./b/..")
    ('/api/x', '/api/x', '/a/')
    """
    return _dot_segments(re.sub(r"/{2,}", "/", unquote(path)))


def _web(href: str) -> str | None:
    """Why an absolute http(s) URL is refused, else None."""
    try:
        parts = urlsplit(href)
        parts.port  # noqa: B018  a port that is not a number raises
    except ValueError:
        return f"not a valid address: {href}"
    if "@" in parts.netloc:
        return f"an address with a user name: {href}"
    if "%" in parts.netloc:
        return f"an address with % in its host: {href}"
    if not parts.hostname:
        return f"an address with no host: {href}"
    normal = origin(href)  # punycode, as a browser compares it
    host = _host(urlsplit(normal).hostname or "") if normal else None
    if host is None or host in own_hosts() or _host(parts.hostname) in own_hosts():
        return f"a link to scrap itself: {href}"
    if API.match(normal_path(parts.path)):
        return f"a link to an /api address: {href}"
    return None


def classify(href: str) -> tuple[str, str]:
    """What an allowed href is, (kind, value): blob (a sha), drawing or excalidraw
    (a drawing's id), tag (a tag as stored), page (a slug), tag-key, site (/ or
    /tags), fragment, mailto or web; ValueError
    saying why for any
    other.

    >>> classify("/p/my-page"), classify("#fn1")
    (('page', 'my-page'), ('fragment', 'fn1'))
    >>> classify("scrap-tag:personal%2Ffamily")
    ('tag', 'personal/family')
    >>> classify("https://example.org/api/x")
    Traceback (most recent call last):
    ValueError: a link to an /api address: https://example.org/api/x
    """
    if m := BLOB.fullmatch(href):
        return "blob", m[1]
    if m := DRAWING.fullmatch(href):
        return "drawing", m[1]
    if m := EXCALIDRAW.fullmatch(href):
        return "excalidraw", m[1]
    if m := TAG.fullmatch(href):
        tag = unquote(m[1], errors="strict")
        return "tag", tag
    if m := PAGE.fullmatch(href):
        return "page", m[1]
    if m := TAG_KEY.fullmatch(href):
        return "tag-key", m[1]
    if href in ("/", "/tags"):  # the site's home and tag list
        return "site", href
    if FRAGMENT.fullmatch(href):
        return "fragment", href[1:]
    if MAILTO.fullmatch(href):
        return "mailto", href
    if ABSOLUTE.fullmatch(href):
        if why := _web(href):
            raise ValueError(why)
        return "web", href
    raise ValueError(f"a link scrap does not publish: {href[:200]}")
