"""Enrich: what the owner does with topics (#261): the index of them, a topic's
sources, and taking one out (the ✕) or putting it back, which queue its synthesis
again. Nobody edits a
synthesis: Regenerate and the owner's guidance are the write-up's (writeup_ops)."""

from typing import Any

from ..store import (
    InvalidError,
    NotFoundError,
    Store,
    now,
    queue_topic,
    roles,
    topics,
    transaction,
)


def index(store: Store) -> list[dict[str, Any]]:
    """The topics, grouped by area (store.topics.index)."""
    with store.connect() as conn:
        return topics.index(conn)


def sources(store: Store, key: str) -> list[dict[str, Any]]:
    """A topic's sources (not in the trash), those the owner excluded too, first
    added first. InvalidError if the page is not a topic."""
    with store.connect() as conn:
        page = store._page_row(conn, key)  # noqa: SLF001
        if not roles.is_topic(conn, page["id"]):
            raise InvalidError("only a topic page has sources")
        return topics.sources(conn, page["id"], excluded=True)


def exclude(store: Store, key: str, source: str, back: bool = False) -> dict[str, Any]:
    """Take a source (by id or slug, in the trash too) out of a topic: it stays,
    excluded, so discovery never adds it again, and the topic's synthesis is queued
    again (with enrich on). back: put an excluded one back in instead (undoing the
    ✕), also queueing it. The topic page. InvalidError if it is not a topic;
    NotFoundError if that page is not one of its sources still in (with back: one
    excluded)."""
    with store.connect() as conn, transaction(conn):
        page = store._page_row(conn, key)  # noqa: SLF001  one transaction
        if not roles.is_topic(conn, page["id"]):
            raise InvalidError("only a topic page has sources")
        other = store._page_row(conn, source, True)  # noqa: SLF001
        change = topics.include if back else topics.exclude
        if not change(conn, page["id"], other["id"], now()):
            what = "an excluded source" if back else "a source"
            raise NotFoundError(f"{source} is not {what} of this topic")
        queue_topic(conn, page["id"])
        return store.page_in(conn, page["id"])
