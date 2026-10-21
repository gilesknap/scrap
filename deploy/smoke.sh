#!/bin/sh
# Smoke test: check /healthz where scrap listens (its Unix socket or local
# port, from ~/.config/scrap/env) and, if given, a public URL.
#   ./deploy/smoke.sh [https://<host>.<tailnet>.ts.net:<port>]
set -eu

env="${XDG_CONFIG_HOME:-$HOME/.config}/scrap/env"
setting() { sed -n "s/^$1=//p" "$env" 2>/dev/null | tail -n 1; }
listen=${SCRAP_LISTEN:-$(setting SCRAP_LISTEN)}
port=${SCRAP_PORT:-$(setting SCRAP_PORT)}

check() { # check URL [curl options]
    url=$1
    shift
    printf '%s/healthz: ' "$url"
    curl -fsS --max-time 10 "$@" "$url/healthz" && echo
}

if [ "$listen" = socket ]; then
    sock="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/scrap/scrap.sock"
    check http://localhost --unix-socket "$sock"
else
    check "http://127.0.0.1:${port:-8790}"
fi
if [ $# -gt 0 ]; then
    check "${1%/}"
fi
