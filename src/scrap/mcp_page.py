"""A page named by its URL: the MCP tools take `https://<host>/p/<slug>` as a slug."""

import re
from urllib.parse import unquote, urlsplit

PAGE_URL = re.compile(r"^/p/([^/]+)/?$")


def page_key(value: str) -> str:
    """The slug in a page URL (`https://<host>/p/<slug>`, any host, a query or
    fragment ignored); any other value, an id or a slug, unchanged. The host is not
    checked: a page of another instance is just not found here."""
    v = value.strip()
    if not v.lower().startswith(("http://", "https://")):
        return value
    try:
        path = urlsplit(v).path
    except ValueError:  # e.g. an unclosed [ in the host
        return value
    m = PAGE_URL.match(path)
    return unquote(m[1]) if m else value
