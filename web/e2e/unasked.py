"""E2E fixture: make a page's first capture one whose images Claude was never asked
about, as a file capture with images is (scrap gc's review page, or a mixed capture
from a build before #380): its kind becomes file and its images' queued jobs go.

Run as `uv run python web/e2e/unasked.py DATA_DIR PAGE_ID` while scrap serves
DATA_DIR (the e2e server runs with ingest off, so the jobs are still queued). Prints
how many image jobs it took away.
"""

import sys

from scrap.store import Store, transaction


def main(data_dir: str, page_id: str) -> None:
    store = Store(data_dir)
    with store.connect() as conn, transaction(conn):
        conn.execute("UPDATE capture SET kind = 'file' WHERE page_id = ?", (page_id,))
        gone = conn.execute(
            "DELETE FROM job WHERE state = 'queued' AND capture_id IN"
            " (SELECT id FROM capture WHERE page_id = ?) AND source_sha256 IN"
            " (SELECT sha256 FROM blob WHERE mime LIKE 'image/%')",
            (page_id,),
        ).rowcount
    print(gone)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
