"""The addresses scrap is reached at ($SCRAP_PUBLIC_URL), and their origins: what a
full-address link to one of its pages (`https://<host>/p/<slug>`) is matched on."""

import os
from functools import cache
from urllib.parse import urlsplit

__all__ = ["origin", "public_origins", "public_urls"]

DEFAULT_PORT = {"http": 80, "https": 443}


def public_urls() -> list[str]:
    """$SCRAP_PUBLIC_URL: the address(es) the service is reached at, comma separated
    (e.g. https://host.tailnet.ts.net:8446). The first makes page links."""
    urls = os.environ.get("SCRAP_PUBLIC_URL", "")
    return [u.strip().rstrip("/") for u in urls.split(",") if u.strip()]


def origin(url: str) -> str | None:
    """A URL's origin as a browser gives it (URL.origin): scheme and host in lower
    case, the port only if it is not the scheme's default; None unless http(s)."""
    try:
        parts = urlsplit(url.strip())
        host, port = parts.hostname, parts.port
    except ValueError:  # an unclosed [ in the host, a port that is not a number
        return None
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORT or not host:
        return None
    if ":" in host:  # IPv6
        host = f"[{host}]"
    return f"{scheme}://{host}" + (
        f":{port}" if port not in (None, DEFAULT_PORT[scheme]) else ""
    )


@cache
def _origins(raw: str) -> tuple[str, ...]:
    found = (origin(u) for u in raw.split(",") if u.strip())
    return tuple(dict.fromkeys(o for o in found if o))


def public_origins() -> tuple[str, ...]:
    """The origins of every address in $SCRAP_PUBLIC_URL, each once, in order: a link
    to /p/<slug> on any of them is a link to that page."""
    return _origins(os.environ.get("SCRAP_PUBLIC_URL", ""))
