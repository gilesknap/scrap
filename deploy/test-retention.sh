#!/bin/sh
# Tests for the retention logic in scrap-backup (no podman needed).
#   ./deploy/test-retention.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0

# make_runs DIR N: N backup runs, oldest first
make_runs() {
    mkdir -p "$1"
    i=1
    while [ "$i" -le "$2" ]; do
        mkdir "$1/2026100${i}T033000Z"
        touch "$1/2026100${i}T033000Z/scrap.db"
        i=$((i + 1))
    done
}

prune() { SCRAP_BACKUPS="$1" SCRAP_BACKUP_KEEP="$2" "$here/scrap-backup" prune; }

expect() { # expect DESCRIPTION EXPECTED ACTUAL
    if [ "$2" = "$3" ]; then
        echo "ok   $1"
    else
        echo "FAIL $1: expected [$2] got [$3]"
        fail=1
    fi
}

listing() { (cd "$1" && find . -mindepth 1 -maxdepth 1 | sort | tr '\n' ' '); }

# Keeps the newest N; a path with spaces does not touch its siblings.
mkdir -p "$tmp/my"
touch "$tmp/my/keep-me"
b="$tmp/my b"
make_runs "$b" 5
prune "$b" 2
expect "keeps newest 2, path with spaces" "./20261004T033000Z ./20261005T033000Z " "$(listing "$b")"
expect "sibling of a spaced path untouched" "./keep-me " "$(listing "$tmp/my")"

# A symlink to a directory and non-backup directories are never removed.
b="$tmp/links"
mkdir -p "$tmp/offsite"
touch "$tmp/offsite/precious"
make_runs "$b" 3
ln -s "$tmp/offsite" "$b/20260101T000000Z"
mkdir "$b/0-notes"
prune "$b" 1
expect "symlink and other dirs kept" \
    "./0-notes ./20260101T000000Z ./20261003T033000Z " "$(listing "$b")"
expect "symlink target untouched" "./precious " "$(listing "$tmp/offsite")"

# Fewer backups than KEEP: nothing removed.
b="$tmp/few"
make_runs "$b" 2
prune "$b" 14
expect "fewer than keep" "./20261001T033000Z ./20261002T033000Z " "$(listing "$b")"

# Bad KEEP values fail loudly and remove nothing.
for keep in 0 00 "" abc -1 2x; do
    b="$tmp/bad"
    rm -rf "$b"
    make_runs "$b" 3
    if prune "$b" "$keep" 2>/dev/null; then
        expect "KEEP='$keep' rejected" "non-zero exit" "exit 0"
    else
        expect "KEEP='$keep' rejected, nothing removed" "3" \
            "$(find "$b" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
    fi
done

exit "$fail"
