"""E2E fixture: a few synthetic pages with tags and kinds, as an import makes them.

Run as `uv run python web/e2e/tagged.py DATA_DIR` while scrap serves DATA_DIR; prints
the slugs as JSON. Run again (a new test worker), it adds nothing: the capture ids are
fixed. Nothing in it is real or private.
"""

import json
import sys
from pathlib import Path

from scrap.store import Store

sys.path.insert(0, str(Path(__file__).parents[2] / "tests"))
from pagehelp import import_page  # noqa: E402

PAGES = [  # title, kind, tags, personal
    ("Zephyr fence repair", "todo", ["zephyr/garden", "diy"], True),
    ("Zephyr fence paint", "todo", ["zephyr/garden"], False),
    ("Zephyr fence book", "consume", ["zephyr", "books"], False),
    ("Zephyr shed plans", "note", ["zephyr/garden/shed"], True),
]

store = Store(sys.argv[1])
slugs = []
for n, (title, kind, tags, personal) in enumerate(PAGES):
    stamp = f"2026-01-0{n + 1}T12:00:00.000Z"
    page = {
        "slug": f"e2e-tagged-{n}", "title": title, "body": f"{title}.",
        "kind": kind, "fields": {"personal": personal}, "tags": tags,
        "created_at": stamp, "updated_at": stamp,
    }  # fmt: skip
    capture = (f"01E2ETAGGED{n:015d}", "note", title, [])
    slugs.append(import_page(store, page, [capture], "e2e")[0])
print(json.dumps(slugs))
