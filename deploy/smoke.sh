#!/bin/sh
# Smoke test: check /healthz where scrap listens (its Unix socket or local
# port, from ~/.config/scrap/env) and, if given, a public URL.
#   ./deploy/smoke.sh [https://<host>.<tailnet>.ts.net:<port>]
set -eu

env="$HOME/.config/scrap/env"
# setting KEY: KEY's value in the env file as systemd reads it: the last
# KEY= line, with surrounding whitespace and one pair of quotes removed.
setting() {
    sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$env" 2>/dev/null |
        tail -n 1 | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' \
        -e "s/^'\\(.*\\)'$/\\1/"
}
# From the env file only, as the unit reads it: SCRAP_LISTEN or SCRAP_PORT exported
# in this shell must not make the test look at a listener the unit does not use.
"$(dirname "$0")/check-env" "$env"
listen=$(setting SCRAP_LISTEN)
port=$(setting SCRAP_PORT)

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
