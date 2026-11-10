"""Placeholders swapped for the site's paths in a checked page (docs/reference/
public-site.md, "Placeholders and files"): ``scrap-blob:<sha>`` for
``/p/<slug>/<name>`` (absolute: a relative link from /p/<slug> resolves under /p/),
``scrap-drawing:<id>`` for its drawing's SVG, ``scrap-diagram:<n>-<theme>`` for a
Mermaid diagram's (#525), ``scrap-excalidraw:<id>`` for the link
that opens that SVG on excalidraw.com, and ``scrap-tag:<tag>`` for ``/t/<key>``.
The check made sure every placeholder is written plainly, once per use, as
RAW_PLACEHOLDER finds it; nothing else in the page changes."""

import re
from urllib.parse import quote, unquote

from ..store import project_tag
from .checker import DIAGRAM_PREFIX, DRAWING_PREFIX, RAW_PLACEHOLDER
from .errors import CheckError
from .links import BLOB, DIAGRAM, DRAWING, EXCALIDRAW, TAG
from .tagkey import tag_key

__all__ = ["EXCALIDRAW_APP", "excalidraw_url", "swap", "without_project_tags"]

EXCALIDRAW_APP = "https://excalidraw.com/#url="
# A tag's chip as the publish mode writes it, and the row of them once emptied
CHIP = re.compile(r'<a\b[^>]*?\shref="scrap-tag:([^"]*)"[^>]*>[^<]*</a>')
NO_CHIPS = re.compile(r'<p class="tags">\s*</p>')


def without_project_tags(html: str) -> str:
    """html without the chips of tags under project/ (#585: they name a local folder),
    which an app from before they were left out still writes, and without the row
    of chips if that empties it.

    >>> without_project_tags('<p class="tags"><a href="scrap-tag:project%2F">x</a></p>')
    ''
    >>> without_project_tags('<a href="scrap-tag:work">#work</a>')
    '<a href="scrap-tag:work">#work</a>'
    """
    out = CHIP.sub(lambda m: "" if project_tag(unquote(m[1])) else m[0], html)
    return NO_CHIPS.sub("", out) if out != html else html


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
        if diagram := DIAGRAM.fullmatch(value):
            return f"/p/{slug}/{names[f'{DIAGRAM_PREFIX}{diagram[1]}-{diagram[2]}']}"
        if opens := EXCALIDRAW.fullmatch(value):
            if not site:  # (publish.drawings refuses this first)
                raise CheckError("Not published: Open in Excalidraw needs the site.")
            return excalidraw_url(site, slug, names[DRAWING_PREFIX + opens[1]])
        tag = TAG.fullmatch(value)
        assert tag is not None  # the check took only these
        return f"/t/{tag_key(unquote(tag[1]))}"

    return RAW_PLACEHOLDER.sub(path, text)
