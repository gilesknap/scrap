"""The HTTP routes for Claude's topic pages (#261): the index, a topic's sources,
taking one out, and the topic mark on search hits (marked). A topic's synthesis is
its write-up, so Regenerate, guidance, versions and Restore are writeup_api's.
Registered by app.create_app (add_routes), which this module builds on, so it is
imported there, not at the top of app.py."""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from . import enrich
from .store import Store, topics


def marked(store: Store, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Search hits, each with topic: whether it is a topic page (the PWA labels
    those)."""
    with store.connect() as conn:
        for hit in hits:
            hit["topic"] = topics.is_topic(conn, hit["id"])
    return hits


def add_routes(app: FastAPI, store: Store, wake: Callable[[], None]) -> None:
    @app.get("/api/topics")
    def topic_index() -> list[dict[str, Any]]:
        """The topics (not in the trash), made from data with no model call, grouped
        by area (the top-level tag most common among a topic's sources, the biggest
        group first): id, slug, title, summary, sources (how many), updated_at and
        area."""
        return enrich.topic_index(store)

    @app.get("/api/pages/{key}/topic/sources")
    def topic_sources(key: str) -> list[dict[str, Any]]:
        """A topic's sources (not in the trash), first added first, with those the
        owner took out (excluded 1); 422 if the page is not a topic."""
        return enrich.topic_sources(store, key)

    @app.delete("/api/pages/{key}/topic/sources/{source}")
    def topic_exclude(key: str, source: str) -> dict[str, Any]:
        """Take a source (id or slug) out of a topic (the ✕): kept as excluded, so
        discovery never adds it again, and the synthesis queued again (with Claude
        on). The topic page; 422 if it is not a topic, 404 if that page is not one
        of its sources."""
        page = enrich.exclude(store, key, source)
        wake()
        return page

    @app.post("/api/pages/{key}/topic/sources/{source}")
    def topic_include(key: str, source: str) -> dict[str, Any]:
        """Put a source the owner took out (id or slug) back into a topic (undoing
        the ✕), and queue the synthesis again (with Claude on). The topic page; 422
        if it is not a topic, 404 if that page is not an excluded source of it."""
        page = enrich.exclude(store, key, source, back=True)
        wake()
        return page
