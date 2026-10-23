#!/bin/sh
# Tests for check-env (no systemd needed). Run: ./deploy/test-check-env.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0

# expect ok|bad CONTENT: check-env accepts or refuses a file with this content.
expect() {
    printf '%s\n' "$2" >"$tmp/env"
    if "$here/check-env" "$tmp/env" >/dev/null 2>&1; then got=ok; else got=bad; fi
    if [ "$got" != "$1" ]; then
        echo "FAIL: wanted $1, got $got for: $2" >&2
        fail=1
    fi
}

expect ok 'SCRAP_LISTEN=socket'
expect ok '# a comment, with an apostrophe: it'"'"'s fine'
expect ok 'SCRAP_IMAGE="ghcr.io/x/scrap:1"'
expect ok "SCRAP_IMAGE='ghcr.io/x/scrap:1'"
expect ok 'A="it'"'"'s"'
expect ok 'A="say \"hi\""'
expect ok 'A='
expect ok '  SCRAP_PORT = 8790  '
# shellcheck disable=SC1003 # the backslash before the quote is the test input
expect bad 'A=bar\'
expect bad 'A=bar\  '
# shellcheck disable=SC1003
expect bad '# comment ending in a backslash \'
expect bad 'A="open'
expect bad "A='open"
expect bad 'A=it'"'"'s'
expect bad 'A="a"b"'
printf 'SCRAP_LISTEN=tcp\nX=bar\\\nSCRAP_LISTEN=socket\n' >"$tmp/env"
if "$here/check-env" "$tmp/env" 2>"$tmp/err"; then
    echo "FAIL: the continued-line example was accepted" >&2
    fail=1
elif ! grep -q 'env:2: line ends in a backslash' "$tmp/err"; then
    echo "FAIL: wrong message: $(cat "$tmp/err")" >&2
    fail=1
fi
"$here/check-env" "$tmp/missing" || { echo "FAIL: missing file" >&2; fail=1; }

[ "$fail" = 0 ] && echo "check-env: all ok"
exit "$fail"
