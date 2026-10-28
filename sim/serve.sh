#!/bin/bash
# Serve sim/out at http://127.0.0.1:${PORT:-9100}/art/x1/index.html: under a sub-path and
# with a doctype added back, as the artifact host serves it. Starts a detached
# python3 -m http.server (log: sim/.host/http.log) unless one already answers.
set -euo pipefail
SIM=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PORT=${PORT:-9100}
HOST="$SIM/.host"
[ -f "$SIM/out/index.html" ] || { echo "no sim/out: run sim/build.sh" >&2; exit 1; }
rm -rf "$HOST/art/x1" && mkdir -p "$HOST/art/x1"
for f in "$SIM"/out/*; do ln -sfn "$f" "$HOST/art/x1/"; done
rm "$HOST/art/x1/index.html"
(echo '<!doctype html>'; cat "$SIM/out/index.html") > "$HOST/art/x1/index.html"
URL="http://127.0.0.1:$PORT/art/x1/index.html"
if ! curl -s --noproxy '*' -o /dev/null "$URL"; then
  (cd "$HOST" && setsid python3 -m http.server "$PORT" --bind 127.0.0.1 > "$HOST/http.log" 2>&1 &)
  sleep 1
fi
echo "$URL"
