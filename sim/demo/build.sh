#!/bin/bash
# The demo cut of the sim (issue #549), from a built sim/out (sim/build.sh), into
# ${DEMO_OUT:-_claude/demo-video}/site: the seed again without the pure test pages
# (mock.py with SIM_DEMO=1) and sim-demo.js after sim.js. sim/out itself is untouched.
set -euo pipefail
DEMO=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SIM=$(dirname "$DEMO")
REPO=$(dirname "$SIM")
OUT=${DEMO_OUT:-$REPO/_claude/demo-video}
SITE="$OUT/site"
[ -f "$SIM/out/sim.js" ] || { echo "no sim/out: run sim/build.sh" >&2; exit 1; }
rm -rf "$SITE" && mkdir -p "$SITE"
cp -r "$SIM/out/." "$SITE/"
SIM_DEMO=1 python3 -I "$SIM/mock.py" "$SIM/fixtures/dump.json" "$SITE"
cp "$DEMO/sim-demo.js" "$SITE/sim-demo.js"
# Load it straight after sim.js, and put the doctype back (build.sh strips it for the host)
python3 -I - "$SITE/index.html" <<'PY'
import sys
f = sys.argv[1]
h = open(f).read()
tag = '<script src="./sim.js"></script>'
assert tag in h
h = "<!doctype html>\n" + h.replace(tag, tag + '\n    <script src="./sim-demo.js"></script>', 1)
open(f, "w").write(h)
PY
echo "$SITE"
