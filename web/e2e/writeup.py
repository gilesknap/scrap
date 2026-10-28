"""E2E fixture: a board page with Claude's write-up (one write-up), by a fake Claude.

Run as `uv run python web/e2e/writeup.py DATA_DIR` while scrap serves DATA_DIR. It
adds a page the write-up links to, saves a capture of a drawn whiteboard, runs its
ingest job and a write-up with a canned answer instead of calling Claude, and
prints {"slug", "target"} as JSON. Nothing in it is real or private.
"""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from draw import BOARD, photo  # noqa: E402

from scrap import claude, enrich, ingest  # noqa: E402
from scrap.store import Store, new_ulid, transaction  # noqa: E402

LEAD = "A capture pipeline from phone to model, by way of a queue."


def answer():
    """The fake Claude: the photo's reading, then the write-up (it links the target)."""

    def fake(model, system, messages, schema, blob, **kw):
        if schema is claude.SCHEMA:
            out = BOARD
        else:
            index = system.split("## Other pages")[1]
            cite = next(
                int(x.split(".")[0]) for x in index.splitlines() if "Retry policy" in x
            )
            out = {
                "summary": LEAD,
                "text": f"## Overview\n\nThe phone sends to the Queue, which feeds"
                f" the Model; see [[{cite}|the retry policy]].\n\n## Open questions"
                f"\n\n- keep originals (?)",
            }
        content = [{"type": "text", "text": json.dumps(out)}]
        usage = {"input_tokens": 1, "output_tokens": 1}
        return claude.Completion(out, content, usage, model, "end_turn")

    return fake


def main(data_dir: str) -> None:
    store = Store(data_dir)
    stamp = "2026-01-01T12:00:00.000Z"
    target = {
        "slug": f"e2e-retry-policy-{new_ulid().lower()[-6:]}",
        "title": "Retry policy", "body": "Retry with backoff.", "kind": "note",
        "fields": {}, "tags": [], "created_at": stamp, "updated_at": stamp,
    }  # fmt: skip
    slug = store.import_page(target, [(new_ulid(), "note", "x", [])], "e2e")[0]
    sha, size = store.put_blob(io.BytesIO(photo()))
    c = store.prepare({"id": new_ulid()}, ["image/png"])
    ref = store.capture(c, [(sha, "image/png", size, "whiteboard.png")], "e2e")[0]
    with store.connect() as conn, transaction(conn):  # claim just this capture's job
        job = conn.execute(
            "UPDATE job SET state = 'running' WHERE capture_id = ? AND state = 'queued'"
            " RETURNING id, capture_id, source_sha256, failures, options",
            (ref["capture_id"],),
        ).fetchone()
    ingest.Worker(store, answer()).process(job)
    assert enrich.write_up(store, answer(), ref["page_id"]) is None
    print(json.dumps({"slug": ref["slug"], "target": slug}))


if __name__ == "__main__":
    main(sys.argv[1])
