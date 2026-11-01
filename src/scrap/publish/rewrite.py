"""Placeholders swapped for the site's paths in a checked page (docs/reference/
public-site.md, "Placeholders and files"): ``scrap-blob:<sha>`` for
``/p/<slug>/<name>`` (absolute: a relative link from /p/<slug> resolves under /p/) and
``scrap-tag:<tag>`` for ``/t/<key>``. The check made sure every placeholder is written
plainly, once per use, as RAW_PLACEHOLDER finds it; nothing else in the page changes."""

import re
from urllib.parse import unquote

from .checker import RAW_PLACEHOLDER
from .links import BLOB, TAG
from .tagkey import tag_key

__all__ = ["swap"]


def swap(text: str, slug: str, names: dict[str, str]) -> str:
    """text with each placeholder replaced (names: each stored sha's name in the
    unit, files.page_files).

    >>> swap('<a href="scrap-tag:a%20b">a b</a>', "p", {})
    '<a href="/t/a-b-c8687a08">a b</a>'
    """

    def path(m: re.Match[str]) -> str:
        value = m[0]
        if blob := BLOB.fullmatch(value):
            return f"/p/{slug}/{names[blob[1]]}"
        tag = TAG.fullmatch(value)
        assert tag is not None  # the check took only these
        return f"/t/{tag_key(unquote(tag[1]))}"

    return RAW_PLACEHOLDER.sub(path, text)
