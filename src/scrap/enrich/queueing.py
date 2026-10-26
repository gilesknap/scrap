"""Enrich: queue a page for Claude (Ask) and the one-off backfill."""

from typing import Any

from ..store import ENRICH_KINDS, Store, queue_enrich, transaction
from ..store.roles import NOT_BY_INGEST


def ask(store: Store, key: str) -> dict[str, Any]:
    """Queue a page for Claude now (the page's Ask Claude); the page as it is then."""
    with store.connect() as conn, transaction(conn):
        page = store._page_row(conn, key)  # noqa: SLF001  one transaction
        queue_enrich(conn, page["id"], "ask")
        return store.page_in(conn, page["id"])


def backfill(store: Store, limit: int | None = None, dry_run: bool = False) -> int:
    """Queue every note, todo, read or link with no tags that Claude has not read (not
    in the trash, and not a photo, whiteboard or document page, nor one with a photo or
    file), oldest first: a one-off command. Returns how many (would be) queued."""
    with store.connect() as conn, transaction(conn):
        ids = [r[0] for r in conn.execute(
            "SELECT p.id FROM page p WHERE p.deleted_at IS NULL"
            f" AND p.kind IN ({','.join('?' * len(ENRICH_KINDS))})"
            " AND NOT EXISTS (SELECT 1 FROM tag t WHERE t.page_id = p.id)"
            " AND p.slug != 'pinned'"
            f" AND {NOT_BY_INGEST.format(p='p')}"
            " AND NOT EXISTS (SELECT 1 FROM enrichment e WHERE e.page_id = p.id)"
            " ORDER BY p.created_at LIMIT ?",
            (*ENRICH_KINDS, -1 if limit is None else limit),
        )]  # fmt: skip
        if not dry_run:
            for page_id in ids:
                queue_enrich(conn, page_id, "backfill")
    return len(ids)
