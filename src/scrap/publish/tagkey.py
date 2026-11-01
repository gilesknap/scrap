"""A tag's key on the public site, ``/t/<key>`` (docs/reference/public-site.md, Tag
keys): computed only here, never in the PWA, and not slug_base (a page slug's rule)."""

import hashlib
import re
import unicodedata

__all__ = ["tag_key"]

_RUN = re.compile(r"[^a-z0-9]+")


def tag_key(tag: str) -> str:
    """The key of a tag as stored: an ASCII slug of it (at most 60 characters), "-",
    and the first 8 hex digits of its SHA-256; the hex alone if the slug is empty.

    >>> tag_key("personal/family")[:16]
    'personal-family-'
    >>> len(tag_key("personal/family"))
    24
    >>> len(tag_key("日本"))
    8
    """
    h = hashlib.sha256(tag.encode()).hexdigest()[:8]
    ascii_ = unicodedata.normalize("NFKD", tag).encode("ascii", "ignore").decode()
    slug = _RUN.sub("-", ascii_.lower()).strip("-")[:60].rstrip("-")
    return f"{slug}-{h}" if slug else h
