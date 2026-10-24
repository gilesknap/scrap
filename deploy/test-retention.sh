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

# Leading zeros are decimal, including 08 and 09; the result is the number.
b="$tmp/zeros"
make_runs "$b" 9
prune "$b" 07
expect "KEEP=07 keeps 7" "7" "$(find "$b" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
prune "$b" 08
expect "KEEP=08 accepted, keeps all 7" "7" "$(find "$b" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
prune "$b" 009
expect "KEEP=009 accepted, keeps all 7" "7" "$(find "$b" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
prune "$b" 02
expect "KEEP=02 keeps newest 2" "./20261008T033000Z ./20261009T033000Z " "$(listing "$b")"

# SCRAP_BACKUPS may itself be a symlink; it is pruned, links inside still are not.
make_runs "$tmp/disk2" 4
ln -s "$tmp/disk2" "$tmp/backups-link"
prune "$tmp/backups-link" 2
expect "symlinked SCRAP_BACKUPS pruned" "./20261003T033000Z ./20261004T033000Z " \
    "$(listing "$tmp/disk2")"

# A missing directory (or dangling symlink) fails loudly.
ln -s "$tmp/nowhere" "$tmp/dangling"
for d in "$tmp/nowhere" "$tmp/dangling"; do
    if err=$(prune "$d" 3 2>&1); then
        expect "missing dir '$d' rejected" "non-zero exit" "exit 0"
    else
        case $err in
        *"is not a directory"*) expect "missing dir rejected with message" ok ok ;;
        *) expect "missing dir rejected with message" "message" "$err" ;;
        esac
    fi
done

# Bad KEEP values fail loudly and remove nothing.
for keep in 0 00 000 "" abc -1 2x 0x1; do
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

# A run in the same second as an existing one fails without deleting it.
b="$tmp/same-second"
bin="$tmp/bin"
make_runs "$b" 1
mkdir -p "$bin"
printf '#!/bin/sh\necho 20261001T033000Z\n' >"$bin/date"
printf '#!/bin/sh\ntouch "%s/podman-called"\nexit 1\n' "$tmp" >"$bin/podman"
chmod +x "$bin/date" "$bin/podman"
if PODMAN="$bin/podman" PATH="$bin:$PATH" SCRAP_BACKUPS="$b" SCRAP_BACKUP_KEEP=3 SCRAP_DATA="$tmp" \
    SCRAP_IMAGE=none "$here/scrap-backup" 2>/dev/null; then
    expect "same-second run rejected" "non-zero exit" "exit 0"
else
    expect "same-second run kept the existing backup" "./scrap.db " \
        "$(listing "$b/20261001T033000Z")"
fi
expect "same-second run stopped before the backup" "no" \
    "$([ -e "$tmp/podman-called" ] && echo yes || echo no)"

exit "$fail"
