"""Enrich: what the owner does with a page's write-up (#256, any page with an image
since #453), or a topic's
synthesis (#261): regenerate it, or steer the next one with guidance. Nobody edits a
write-up's text: it is only ever made by Claude, and a new one replaces it."""

from typing import Any

from ..store import (
    InvalidError,
    Store,
    now,
    queue_topic,
    queue_writeup,
    roles,
    transaction,
    writeups,
)
from .constants import MAX_GUIDANCE


def regenerate(store: Store, key: str) -> dict[str, Any]:
    """Queue a page's write-up, or a topic's synthesis, again (Regenerate; the first
    time, for a page that is not a board, on request: #453), with the guidance as it
    is when it runs; the page as it is then. InvalidError if it is neither a topic nor
    has an image (read, and not a list of actions)."""
    with store.connect() as conn, transaction(conn):
        page = store._page_row(conn, key)  # noqa: SLF001  one transaction
        # A topic first here, a board first in roles.writeup_type (see its TODO)
        if roles.is_topic(conn, page["id"]):
            queue_topic(conn, page["id"])
        elif roles.has_image(conn, page["id"]):  # a board, or on request (#453)
            queue_writeup(conn, page["id"])
        else:
            raise InvalidError(
                "only a page with an image (read, not a list of actions), or a topic,"
                " has a write-up"
            )
        return store.page_in(conn, page["id"])


def set_guidance(
    store: Store, key: str, text: str | None, author: str
) -> dict[str, Any]:
    """Keep the owner's guidance for a page's next write-up (empty: none); the page.
    It is used by the next one made, and kept with it."""
    if text is not None and len(text) > MAX_GUIDANCE:
        raise InvalidError(f"guidance is at most {MAX_GUIDANCE} characters")
    with store.connect() as conn, transaction(conn):
        page = store._page_row(conn, key)  # noqa: SLF001  one transaction
        writeups.set_guidance(conn, page["id"], text, author, now())
        return store.page_in(conn, page["id"])
