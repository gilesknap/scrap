"""E2E fixture: mark tags on a page as Claude's, as an ingest or enrich read does.

Run as `uv run python web/e2e/chips.py DATA_DIR PAGE_ID TAG...` while scrap serves
DATA_DIR. The tags must be on the page already. Nothing in it is real or private.
"""

import sys

from scrap.store import Store, transaction

data, page_id, *tags = sys.argv[1:]
store = Store(data)
with store.connect() as conn, transaction(conn):
    conn.executemany(
        "INSERT INTO model_tag VALUES (?, ?, 'on', 'e2e', '2026-01-01T00:00:00.000Z')"
        " ON CONFLICT DO NOTHING",
        [(page_id, t) for t in tags],
    )
