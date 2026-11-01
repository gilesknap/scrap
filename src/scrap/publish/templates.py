"""The site's own pages, as plain templates (no Markdown): the home page (the public
pages, newest first, with their tags and Pagefind's search box), the tag list, one
tag's page and the 404 (docs/reference/public-site.md, "What scrap builds"). Built
only from the kept copies' meta.json, in sorted order and with no build time, so the
same copies give the same bytes.

The classes they use (site-head, site-list, chips, chip, site-search, when) are
styled by /assets/page.css, the PWA build's."""

from html import escape
from typing import Any

from .tagkey import tag_key

__all__ = ["home", "not_found", "tag_page", "tags_page"]

# home's CSP lets it run only the site's own scripts: Pagefind's, and scrap-search.js
SEARCH = (
    '<link rel="stylesheet" href="/assets/pagefind-ui.css">\n'
    '<script src="/pagefind/pagefind-ui.js" defer></script>\n'
    '<script src="/pagefind/scrap-search.js" defer></script>\n'
)


def _document(title: str, body: str, head: str = "") -> bytes:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{escape(title)}</title>\n"
        '<link rel="stylesheet" href="/assets/page.css">\n'
        f"{head}</head>\n"
        '<body class="site">\n<header class="site-head"><a href="/">Pages</a>'
        ' · <a href="/tags">Tags</a></header>\n'
        f"<main>\n{body}</main>\n</body>\n</html>\n"
    ).encode()


def _chips(tags: list[str]) -> str:
    if not tags:
        return ""
    chips = "".join(
        f'<a class="chip" href="/t/{tag_key(t)}">{escape(t)}</a>' for t in sorted(tags)
    )
    return f' <span class="chips">{chips}</span>'


def _row(slug: str, meta: dict[str, Any], tags: bool = True) -> str:
    when = str(meta.get("published_at") or "")
    date = f' <time class="when" datetime="{escape(when)}">{escape(when[:10])}</time>'
    chips = _chips(list(meta.get("tags") or [])) if tags else ""
    title = escape(str(meta.get("title") or slug))
    return f'<li><a href="/p/{slug}">{title}</a>{date if when else ""}{chips}</li>\n'


def _list(rows: str) -> str:
    return f'<ul class="site-list">\n{rows}</ul>\n' if rows else ""


def home(pages: list[tuple[str, dict[str, Any]]]) -> bytes:
    """index.html: pages ((slug, meta), newest published first) and the search box."""
    rows = "".join(_row(slug, meta) for slug, meta in pages)
    none = "" if rows else "<p>No pages are public yet.</p>\n"
    body = (
        '<h1>Pages</h1>\n<div id="search" class="site-search"></div>\n'
        f"{_list(rows)}{none}"
    )
    return _document("Pages", body, SEARCH)


def tags_page(tags: dict[str, list[tuple[str, dict[str, Any]]]]) -> bytes:
    """tags.html: every tag a public page has, with its pages."""
    parts = []
    for tag in sorted(tags):
        rows = "".join(_row(slug, meta, False) for slug, meta in tags[tag])
        parts.append(
            f'<h2><a href="/t/{tag_key(tag)}">{escape(tag)}</a></h2>\n{_list(rows)}'
        )
    body = "<h1>Tags</h1>\n" + ("".join(parts) or "<p>No tags yet.</p>\n")
    return _document("Tags", body)


def tag_page(tag: str, pages: list[tuple[str, dict[str, Any]]]) -> bytes:
    """t/<key>/index.html: one tag's pages."""
    rows = "".join(_row(slug, meta) for slug, meta in pages)
    return _document(tag, f"<h1>{escape(tag)}</h1>\n{_list(rows)}")


def not_found() -> bytes:
    """404.html, served for every path the site does not have: it runs no script."""
    return _document(
        "Not found",
        "<h1>Not found</h1>\n<p>There is no public page here (it may have been made"
        ' private). <a href="/">All pages</a></p>\n',
    )
