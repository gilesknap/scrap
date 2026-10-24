"""Types the store passes around."""

from typing import NamedTuple


class Meta(NamedTuple):
    """A page's kind, whether it is fixed (kind_fixed), and tags (sorted): what
    page_meta_rev keeps of it, before and after a change."""

    kind: str
    fixed: int
    tags: list[str]
