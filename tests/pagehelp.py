"""A test helper: a page written whole, as an import writes it (its dates, kind
fixed, captures with source 'import'), so tests can build pages of that shape."""

from collections.abc import Sequence
from typing import Any

from scrap.store import Store
from scrap.store.constants import BlobRef


def import_page(
    store: Store,
    p: dict[str, Any],
    captures: Sequence[tuple[str, str, str | None, Sequence[BlobRef]]],
    author: str,
    enqueue: bool = False,
) -> tuple[str, bool]:
    """Store.import_page with every capture's files queued for ingest (enqueue: its
    photos and files, as a capture would) or none. Returns the slug and whether it
    is new."""
    slug, new, _ = store.import_page(p, captures, author, enqueue, enqueue)
    return slug, new
