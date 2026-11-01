"""Placeholders swapped for the site's paths in a checked page (docs/reference/
public-site.md, "Placeholders and files"): ``scrap-blob:<sha>`` for
``/p/<slug>/<name>`` (absolute: a relative link from /p/<slug> resolves under /p/),
``scrap-drawing:<id>`` for its drawing's SVG, ``scrap-excalidraw:<id>`` for the link
that opens that SVG on excalidraw.com, and ``scrap-tag:<tag>`` for ``/t/<key>``.
The check made sure every placeholder is written plainly, once per use, as
RAW_PLACEHOLDER finds it; nothing else in the page changes."""

import re
from urllib.parse import quote, unquote

from .checker import DRAWING_PREFIX, RAW_PLACEHOLDER
from .links import BLOB, DRAWING, EXCALIDRAW, TAG
from .tagkey import tag_key

__all__ = ["EXCALIDRAW_APP", "excalidraw_url", "swap"]

EXCALIDRAW_APP = "https://excalidraw.com/#url="


def excalidraw_url(site: str, slug: str, name: str) -> str:
    """The link that opens a published drawing on excalidraw.com: its #url= (which
    excalidraw.com fetches in the reader's browser and loads, as a file opened
    there), the SVG's address on the site, encoded as encodeURIComponent does.

    >>> excalidraw_url("https://pages.example", "a", "img-1-0123456789.svg")
    'https://excalidraw.com/#url=https%3A%2F%2Fpages.example%2Fp%2Fa%2Fimg-1-0123456789.svg'
    """
    return EXCALIDRAW_APP + quote(f"{site}/p/{slug}/{name}", safe="-_.!~*'()")


def swap(text: str, slug: str, names: dict[str, str], site: str | None = None) -> str:
    """text with each placeholder replaced (names: each stored sha's name in the
    unit, files.page_files; site: the public site's address, for Open in
    Excalidraw).

    >>> swap('<a href="scrap-tag:a%20b">a b</a>', "p", {})
    '<a href="/t/a-b-c8687a08">a b</a>'
    """

    def path(m: re.Match[str]) -> str:
        value = m[0]
        if blob := BLOB.fullmatch(value):
            return f"/p/{slug}/{names[blob[1]]}"
        if drawing := DRAWING.fullmatch(value):
            return f"/p/{slug}/{names[DRAWING_PREFIX + drawing[1]]}"
        if (opens := EXCALIDRAW.fullmatch(value)) and site:
            return excalidraw_url(site, slug, names[DRAWING_PREFIX + opens[1]])
        tag = TAG.fullmatch(value)
        assert tag is not None  # the check took only these
        return f"/t/{tag_key(unquote(tag[1]))}"

    return RAW_PLACEHOLDER.sub(path, text)
