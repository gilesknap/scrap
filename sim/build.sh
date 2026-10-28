#!/bin/bash
# Build the scrap sim from this checkout into sim/out (see sim/README.md).
# Needs web/node_modules (npm --prefix web ci) and python3.
set -euo pipefail
SIM=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(dirname "$SIM")
OUT="$SIM/out"
cd "$REPO/web"
[ -d node_modules ] || { echo "no web/node_modules: run npm --prefix web ci" >&2; exit 1; }
# The config imports web/vite.config.ts and must sit under web/; npm ci wipes node_modules
mkdir -p node_modules/.sim && cp "$SIM/vite.sim.config.ts" node_modules/.sim/
rm -rf "$OUT" && mkdir -p "$OUT"
SIM_DIR="$SIM" npx vite build --config node_modules/.sim/vite.sim.config.ts --logLevel warn
rm -f "$OUT/sw.js"
cp "$SIM/sim.js" "$OUT/sim.js"
cp -r "$SIM/fixtures/blobs" "$OUT/blobs"
python3 -I "$SIM/mock.py" "$SIM/fixtures/dump.json" "$OUT"
# The host refuses U+FFFD in files: escape it (markdown-it's, in template literals). And it
# wraps the page in its own document, so drop the doctype and the html, head and body tags.
python3 -I - "$OUT" <<'PY'
import glob, sys, re, os
os.chdir(sys.argv[1])
for f in glob.glob("**/*.js", recursive=True):
    s = open(f, encoding="utf-8").read()
    if "�" in s: open(f, "w", encoding="utf-8").write(s.replace("�", "\\uFFFD"))
h = open("index.html").read()
h = re.sub(r"<!doctype html>\s*", "", h, flags=re.I)
h = re.sub(r"</?(?:html|head|body)(?:\s[^>]*)?>\s*", "", h)
open("index.html", "w").write(h)
PY
echo "$(du -sh "$OUT" | cut -f1) in $(find "$OUT" -type f | wc -l) files: $OUT"
