"""The site's derived units, built only from the kept copies (docs/reference/
public-site.md, "What scrap builds"): ``home`` (index.html, tags.html, 404.html), a
``t/<key>`` for each tag a public page has, ``pagefind`` and ``assets`` (page.css,
katex.css and KaTeX's fonts from the PWA's build, and Pagefind's UI stylesheet).
Deterministic: the same copies (and the same build) give the same bytes."""

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from .kept import Kept
from .search import UI_CSS, build_index, index_text
from .tagkey import tag_key
from .templates import home, not_found, tag_page, tags_page

__all__ = ["ASSET_TYPES", "assets", "build"]

ASSET_TYPES = (".css", ".woff", ".woff2", ".ttf")
log = logging.getLogger(__name__)
_warned = False


def assets(static: Path, ui_css: bytes) -> dict[str, bytes]:
    """The assets unit: page.css, katex.css and fonts/* from static (the PWA build's
    public/ folder), and Pagefind's UI stylesheet. Missing (no PWA build): only the
    stylesheet, logged once, so pages show unstyled rather than not at all."""
    global _warned
    files: dict[str, bytes] = {}
    for name in ("page.css", "katex.css"):
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
    records = sorted(
        (f"/p/{slug}", str(meta.get("title") or slug),
         index_text(kept.html(slug)))
        for slug, meta in pages
    )  # fmt: skip
    index, ui_css = build_index(records)
    units["pagefind"] = index
    units["assets"] = assets(static, ui_css)
    return units
