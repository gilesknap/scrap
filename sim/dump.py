"""Dump a seeded scratch scrap server into the sim's fixtures.

    python3 sim/dump.py [BASE] [FIXTURES]

BASE is the server (default http://127.0.0.1:8765), FIXTURES the folder to write
(default: fixtures/ beside this file). It writes FIXTURES/dump.json, in the shape
sim.js reads:

    {"pages": [GET /api/pages/{id} for each of GET /api/pages?limit=500],
     "drawings": {"<capture id>/<sha>": {"current": GET .../drawing,
                                          "versions": GET .../drawing/versions}}}

and FIXTURES/blobs/ with each photo's original (<sha>) and its previews
(<sha>-480.jpg, <sha>-2048.jpg), the names sim.js asks the host for.

Run it after seed.py, on the same server (see sim/README.md). The ids and times
come out new each time, and mock.py finds pages by slug, so check its output still
matches before you commit new fixtures.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "fixtures"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(path):
    with OPENER.open(BASE + path) as r:
        return r.read()


def get_json(path):
    return json.loads(get(path))


pages = [get_json(f"/api/pages/{p['id']}") for p in get_json("/api/pages?limit=500")]
drawings = {}
blobs = set()
for p in pages:
    for c in p["captures"]:
        for b in c["blobs"]:
            sha = b["sha256"]
            blobs.add(sha)
            base = f"/api/captures/{c['id']}/photos/{sha}/drawing"
            try:
                current = get_json(base)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                continue
            drawings[f"{c['id']}/{sha}"] = {
                "current": current,
                "versions": get_json(base + "/versions"),
            }

(OUT / "blobs").mkdir(parents=True, exist_ok=True)
(OUT / "dump.json").write_text(json.dumps({"pages": pages, "drawings": drawings}) + "\n")
for sha in sorted(blobs):
    (OUT / "blobs" / sha).write_bytes(get(f"/api/blobs/{sha}"))
    for size in (480, 2048):
        data = get(f"/api/blobs/{sha}/preview?size={size}")
        (OUT / "blobs" / f"{sha}-{size}.jpg").write_bytes(data)
print(f"{len(pages)} pages, {len(drawings)} drawings, {len(blobs)} files -> {OUT}")
