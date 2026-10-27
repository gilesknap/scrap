"""E2E fixture: read a page's PDFs and text files now, as the ingest worker would.

Run as `uv run python web/e2e/readfiles.py DATA_DIR PAGE_ID` while scrap serves
DATA_DIR (the e2e server runs with ingest off, so files wait unread). It claims the
page's queued file jobs (not its photos') and runs each through the worker, which
reads a file locally, with no Claude call. Prints how many it ran.
"""

import sys

from scrap import ingest
from scrap.store import Store, transaction


def never(*_):
    raise AssertionError("a file is read locally: Claude is never called")


def main(data_dir: str, page_id: str) -> None:
    store = Store(data_dir)
    with store.connect() as conn, transaction(conn):
        jobs = conn.execute(
            "UPDATE job SET state = 'running' WHERE state = 'queued' AND capture_id IN"
            " (SELECT id FROM capture WHERE page_id = ?) AND source_sha256 IN"
            " (SELECT sha256 FROM blob WHERE mime NOT LIKE 'image/%')"
            " RETURNING id, capture_id, source_sha256, failures, options",
            (page_id,),
        ).fetchall()
    worker = ingest.Worker(store, never)
    for job in jobs:
        worker.process(job)
    print(len(jobs))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
