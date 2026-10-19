#!/bin/sh
# Smoke test: check /healthz on the local port and, if given, a public URL.
#   ./deploy/smoke.sh [https://<host>.<tailnet>.ts.net:<port>]
set -eu

env="${XDG_CONFIG_HOME:-$HOME/.config}/scrap/env"
port=$(sed -n 's/^SCRAP_PORT=//p' "$env" 2>/dev/null || true)
port=${SCRAP_PORT:-${port:-8790}}

check() {
    printf '%s/healthz: ' "$1"
    curl -fsS --max-time 10 "$1/healthz" && echo
}

check "http://127.0.0.1:$port"
if [ $# -gt 0 ]; then
    check "${1%/}"
fi
