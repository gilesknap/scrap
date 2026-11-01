"""Types the store passes around."""

from typing import Any, NamedTuple


class Meta(NamedTuple):
    """A page's kind, whether it is fixed (kind_fixed), tags (sorted) and whether it
    is public (page.public, ADR 43): what page_meta_rev keeps of it, before and after
    a change."""

    kind: str
    fixed: int
    tags: list[str]
    public: int = 0


class FieldEdit(NamedTuple):
    """Changes to a page's fields beside its kind's defaults (page_meta_rev's
    fields_added and fields_was): put sets these (None takes one off); drop and was
    are a revert's: the values the change it undoes set (taken off, or changed back,
    unless changed since) and those they had before (given back)."""

    put: dict[str, Any] = {}
    drop: dict[str, Any] = {}
    was: dict[str, Any] = {}
