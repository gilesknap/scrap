"""Enrich: a successful write-up call (a board's, or a topic's synthesis), stored:
its run finished, and the write-up a new current version."""

import json
from typing import Any

from .. import claude
from ..runs import record
from ..store import Store, now, transaction, writeups


def written(
    store: Store,
    run_id: int,
    page_id: str,
    done: claude.Completion,
    version: str,
    out: dict[str, Any],
    guidance: str | None,
) -> None:
    """A write-up's (or a topic's synthesis's) run, ok, and, unless its page is in the
    trash now, the write-up as a new current version, the page indexed again."""
    with store.connect() as conn, transaction(conn):
        record(conn, "enrich_run", run_id, done, status="ok", output=json.dumps(out))
        alive = conn.execute(
            "SELECT 1 FROM page WHERE id = ? AND deleted_at IS NULL", (page_id,)
        ).fetchone()
        if alive:
            writeups.put(
                conn, page_id, now(), producer=done.served_model, run_id=run_id,
                prompt_version=version, summary=out["summary"], text=out["text"],
                guidance=guidance,
            )  # fmt: skip
            store.reindex(conn, page_id)
