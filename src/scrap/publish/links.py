"""Which ``href`` a published page may have (docs/reference/public-site.md, "Links
scrap accepts"): matched in full (re.fullmatch) after entity decoding, which the parser
has done. Anything not listed is refused: a relative /api/..., //..., /\\...,
javascript:, data: and the rest."""

import re
from urllib.parse import unquote, urlsplit

from ..public import origin, public_origins

__all__ = ["BLOB", "ID", "PAGE", "TAG", "TAG_KEY", "classify", "own_hosts"]

BLOB = re.compile(r"scrap-blob:([0-9a-f]{64})")
# encodeURIComponent's output: what the publish mode writes a tag as
TAG = re.compile(r"scrap-tag:([A-Za-z0-9%._~!*'()-]+)")
PAGE = re.compile(r"/p/([a-z0-9-]{1,120})")
TAG_KEY = re.compile(r"/t/([a-z0-9-]{1,80})")
ID = re.compile(r"[a-z0-9_-]{1,80}")  # render.ts's heading and footnote ids
FRAGMENT = re.compile(r"#[a-z0-9_-]{1,80}")
MAILTO = re.compile(r"mailto:[^\s\x00-\x1f\x7f]+", re.IGNORECASE)
ABSOLUTE = re.compile(r"https?://[^\s\x00-\x1f\x7f\\]+", re.IGNORECASE)
API = re.compile(r"/api(?:/|$)", re.IGNORECASE)


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


def _web(href: str) -> str | None:
    """Why an absolute http(s) URL is refused, else None."""
    try:
        parts = urlsplit(href)
        parts.port  # noqa: B018  a port that is not a number raises
    except ValueError:
        return f"not a valid address: {href}"
    if "@" in parts.netloc:
        return f"an address with a user name: {href}"
    if not parts.hostname:
        return f"an address with no host: {href}"
    normal = origin(href)  # punycode, as a browser compares it
    host = _host(urlsplit(normal).hostname or "") if normal else None
    if host is None or host in own_hosts() or _host(parts.hostname) in own_hosts():
        return f"a link to scrap itself: {href}"
    if API.match(unquote(parts.path)):
        return f"a link to an /api address: {href}"
    return None


def classify(href: str) -> tuple[str, str]:
    """What an allowed href is, (kind, value): blob (a sha), tag (a tag as stored),
    page (a slug), tag-key, site (/ or /tags), fragment, mailto or web; ValueError
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
