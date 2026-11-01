"""E2E fixture: a maths page with a diagram Claude drew (#521), as add_svg stores it.

Run as `uv run python web/e2e/claudesvg.py DATA_DIR` while scrap serves DATA_DIR. It
makes a page, adds an SVG to it as add_svg does (a capture of source mcp, author
claude, its label as the embed's alt), and a second one with a reading from before
#521 (a done job and Claude's description, as an old add_svg had), and prints
{"slug", "page_id", "sha256", "old"} as JSON. Nothing in it is real or private.
"""

import io
import json
import sys

from scrap import svg
from scrap.ingest.jobs import put_derived
from scrap.store import Store, new_ulid, now, transaction

NS = 'xmlns="http://www.w3.org/2000/svg"'
TRI = (
    f'<svg {NS} viewBox="0 0 320 150"><title>Triangle ABC</title>'
    '<path d="M110 25 V125 H250 Z" fill="none" stroke="#222" stroke-width="3"/>'
    '<text x="104" y="20">A</text><text x="254" y="144">C</text></svg>'
)
PQR = (
    f'<svg {NS} viewBox="0 0 320 150"><title>Triangle PQR</title>'
    '<path d="M160 22 L80 125 H240 Z" fill="none" stroke="#222" stroke-width="3"/>'
    "</svg>"
)
LABEL = "Right triangle ABC, AB 5 cm, BC 12 cm"


def add(store: Store, slug: str, markup: str, alt: str, name: str) -> tuple[str, str]:
    clean = svg.sanitise(markup.encode())
    sha, size = store.put_blob(io.BytesIO(clean))
    cid = new_ulid()
    store.add_photos(slug, cid, [(sha, svg.SVG, size, name)], "claude", "mcp", alt=alt)
    return cid, sha


def main(data_dir: str) -> None:
    store = Store(data_dir)
    c = store.prepare(
        {"id": new_ulid(), "text": "Maths paper e2e\n\nQ3 Work out AC."}, []
    )
    ref = store.capture(c, [], "e2e")[0]
    _, sha = add(store, ref["slug"], TRI, LABEL, "triangle-abc.svg")
    old_cid, old = add(store, ref["slug"], PQR, "Isosceles triangle PQR", "pqr.svg")
    stamp = now()
    with store.connect() as conn, transaction(conn):  # read before #521, as add_svg's
        conn.execute(
            "INSERT INTO job (kind, capture_id, source_sha256, options, state,"
            " run_after,"
            " created_at, updated_at) VALUES ('ingest', ?, ?, '{}', 'done', ?, ?, ?)",
            (old_cid, old, stamp, stamp, stamp),
        )
        put_derived(
            conn, old_cid, old, "description", "claude-e2e", stamp,
            text="OLD READING of an isosceles triangle", data={"kind": "diagram"},
        )  # fmt: skip
    print(json.dumps({**ref, "sha256": sha, "old": old}))


if __name__ == "__main__":
    main(sys.argv[1])
