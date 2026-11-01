"""The site's derived units, built only from the kept copies (docs/reference/
public-site.md, "What scrap builds"): ``home`` (index.html, tags.html, 404.html), a
``t/<key>`` for each tag a public page has, ``pagefind`` and ``assets`` (page.css,
katex.css, prefs.js (the theme and width switches, #519) and KaTeX's fonts from the
PWA's build, and Pagefind's UI stylesheet).
Deterministic: the same copies (and the same build) give the same bytes.

If Pagefind fails (search.SearchError), the units have no pagefind (and no assets,
unless an earlier build's UI stylesheet is cached): the site keeps the last ones it
was sent, and pending() says the derived units are not all built."""

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from .kept import Kept
from .search import UI_CSS, SearchError, build_index, cached_css, index_text
from .tagkey import tag_key
from .templates import home, not_found, tag_page, tags_page

__all__ = ["ASSET_TYPES", "SEARCH", "assets", "build", "pending"]

ASSET_TYPES = (".css", ".woff", ".woff2", ".ttf")
PREFS = "prefs.js"  # the one script outside pagefind (the receiver allows only it)
SEARCH = "search"  # the cached Pagefind build, in the kept copies' folder
log = logging.getLogger(__name__)
_warned = False


def assets(static: Path, ui_css: bytes) -> dict[str, bytes]:
    """The assets unit: page.css, katex.css, prefs.js and fonts/* from static (the PWA
    build's public/ folder), and Pagefind's UI stylesheet. Missing (no PWA build):
    only the
    stylesheet, logged once, so pages show unstyled rather than not at all."""
    global _warned
    files: dict[str, bytes] = {}
    for name in ("page.css", "katex.css", PREFS):
        if (static / name).is_file():
            files[name] = (static / name).read_bytes()
    fonts = static / "fonts"
    if fonts.is_dir():
        for font in sorted(fonts.iterdir()):
            if font.is_file() and font.name.lower().endswith(ASSET_TYPES):
                files[f"fonts/{font.name}"] = font.read_bytes()
    if not files and not _warned:
        _warned = True
        log.warning(
            "publish: no PWA build in %s: the site's pages are unstyled", static
        )
    files[UI_CSS] = ui_css or b"/* Pagefind's UI stylesheet */\n"
    return files


def _newest_first(pages: list[tuple[str, dict[str, Any]]]):
    return sorted(pages, key=lambda p: (str(p[1].get("published_at") or ""), p[0]),
                  reverse=True)  # fmt: skip


def build(kept: Kept, static: Path) -> dict[str, dict[str, bytes]]:
    """Every derived unit, by unit name, from the kept copies."""
    pages = []
    for slug in kept.slugs():
        meta = kept.meta(slug)
        if meta is not None:
            pages.append((slug, meta))
    pages = _newest_first(pages)
    tags: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for slug, meta in pages:
        for tag in sorted(set(meta.get("tags") or [])):
            tags[str(tag)].append((slug, meta))
    units: dict[str, dict[str, bytes]] = {
        "home": {
            "index.html": home(pages),
            "tags.html": tags_page(tags),
            "404.html": not_found(),
        }
    }
    for tag, tagged in tags.items():
        units[f"t/{tag_key(tag)}"] = {"index.html": tag_page(tag, tagged)}
    stored = kept.digests()
    records = sorted(
        (f"/p/{slug}", str(meta.get("title") or slug),
         _text(kept, slug, stored.get(f"p/{slug}")))
        for slug, meta in pages
    )  # fmt: skip
    for gone in set(_TEXTS) - {slug for slug, _ in pages}:
        del _TEXTS[gone]
    cache = kept.root / SEARCH
    try:
        index, ui_css = build_index(records, cache)
        units["pagefind"] = index
    except SearchError as e:  # the site keeps its last index
        log.warning("publish: the search index is pending: %s", e)
        ui_css = cached_css(cache)
    if ui_css is not None:
        units["assets"] = assets(static, ui_css)
    return units


# Each kept page's index text, by its slug and the digest scrap stored for it: a copy
# is replaced whole (a new digest) or not at all, so an unchanged page is not parsed
# with html5lib again on every build. Pages no longer kept drop out at the next build.
_TEXTS: dict[str, tuple[str, str]] = {}


def _text(kept: Kept, slug: str, stored: str | None) -> str:
    hit = _TEXTS.get(slug)
    if stored is not None and hit is not None and hit[0] == stored:
        return hit[1]
    text = index_text(kept.html(slug), lambda name: kept.file(slug, name))
    if stored is not None:
        _TEXTS[slug] = (stored, text)
    return text


def pending(units: dict[str, dict[str, bytes]]) -> bool:
    """Whether a build left a unit out (Pagefind failed): the site keeps its last."""
    return "pagefind" not in units or "assets" not in units
