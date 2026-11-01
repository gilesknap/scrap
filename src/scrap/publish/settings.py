"""Where scrap publishes to (docs/reference/public-site.md, Settings):
``SCRAP_PUBLISH_TO``, the receiver's base URL; ``SCRAP_PUBLISH_SITE``, the public site's
base URL for the links scrap shows; ``SCRAP_PUBLISH_TOKEN_FILE``, a file holding the
receiver's token (only from a file: the chart mounts the Secret, never an environment
variable). Without SCRAP_PUBLISH_TO and the token file, publishing is off."""

import os
import re
from pathlib import Path

__all__ = [
    "MIN_TOKEN",
    "check",
    "enabled",
    "page_url",
    "publish_site",
    "publish_to",
    "static_dir",
    "token",
]

MIN_TOKEN = 32  # the receiver refuses a shorter token
URL = re.compile(r"https?://[^\s/?#]+(/[^\s?#]*)?", re.IGNORECASE)
# The built PWA (npm --prefix web run build): its public/ folder holds what the site's
# assets unit carries, page.css, katex.css and fonts/
STATIC = Path(__file__).resolve().parent.parent / "static"


def _url(name: str) -> str | None:
    value = os.environ.get(name, "").strip().rstrip("/")
    return value or None


def publish_to() -> str | None:
    """$SCRAP_PUBLISH_TO: the receiver's base URL, or None."""
    return _url("SCRAP_PUBLISH_TO")


def publish_site() -> str | None:
    """$SCRAP_PUBLISH_SITE: the public site's base URL, or None."""
    return _url("SCRAP_PUBLISH_SITE")


def token() -> str | None:
    """The receiver's token: the stripped content of $SCRAP_PUBLISH_TOKEN_FILE, read
    each time (so a rotated Secret is picked up), None when unset, unreadable, short
    or holding whitespace (check says why at start)."""
    path = os.environ.get("SCRAP_PUBLISH_TOKEN_FILE", "").strip()
    if not path:
        return None
    try:
        value = Path(path).read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if len(value) < MIN_TOKEN or any(c.isspace() for c in value):
        return None
    return value


def enabled() -> bool:
    """Whether publishing is on: a receiver URL and a token."""
    return publish_to() is not None and token() is not None


def check() -> None:
    """At start: refuse settings that cannot work (a receiver URL that is not http(s),
    a token file given but unreadable, shorter than MIN_TOKEN or holding whitespace),
    so publishing never silently turns itself off."""
    to = publish_to()
    if to is not None and not URL.fullmatch(to):
        raise SystemExit(f"SCRAP_PUBLISH_TO must be an http(s) URL, not {to!r}")
    site = publish_site()
    if site is not None and not URL.fullmatch(site):
        raise SystemExit(f"SCRAP_PUBLISH_SITE must be an http(s) URL, not {site!r}")
    path = os.environ.get("SCRAP_PUBLISH_TOKEN_FILE", "").strip()
    if path and token() is None:
        raise SystemExit(
            "SCRAP_PUBLISH_TOKEN_FILE: cannot read a token from"
            f" {path!r} (at least {MIN_TOKEN} characters, no whitespace)"
        )


def page_url(slug: str) -> str | None:
    """A page's address on the public site, None without SCRAP_PUBLISH_SITE."""
    site = publish_site()
    return f"{site}/p/{slug}" if site else None


def static_dir() -> Path:
    """The PWA build's public/ folder: page.css, katex.css and fonts/ (the assets
    unit), from $SCRAP_WEB_DIR when set, as the PWA itself is served."""
    return Path(os.environ.get("SCRAP_WEB_DIR") or STATIC) / "public"
