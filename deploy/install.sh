#!/bin/sh
# Install scrap as systemd user services for the current (non-root) user.
# Run from a clone of the scrap repo:  ./deploy/install.sh
# Safe to re-run: it updates the units, never overwrites ~/.config/scrap/env or
# ~/.config/scrap/ingest.env, and restarts scrap if its image or unit changed.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
conf="${XDG_CONFIG_HOME:-$HOME/.config}/scrap"
data="${XDG_DATA_HOME:-$HOME/.local/share}/scrap"
lib="$HOME/.local/lib/scrap"

if [ "$(id -u)" = 0 ]; then
    echo "Run this as the user that will own scrap, not as root." >&2
    exit 1
fi
command -v podman >/dev/null || { echo "podman is not installed." >&2; exit 1; }
if ! grep -q "^$(id -un):" /etc/subuid 2>/dev/null; then
    echo "Warning: no /etc/subuid entry for $(id -un); rootless podman needs one." >&2
fi
if ! systemctl --user show-environment >/dev/null 2>&1; then
    echo "systemctl --user does not work in this shell. Log in as $(id -un)" >&2
    echo "directly (ssh, or: sudo machinectl shell $(id -un)@) and re-run." >&2
    exit 1
fi

mkdir -p "$units" "$conf" "$lib" "$data/data" "$data/backups"

if [ ! -e "$conf/env" ]; then
    cat >"$conf/env" <<ENV
# scrap settings, read by scrap.service and scrap-backup.service.
# Plain KEY=value lines: systemd reads this file, not a shell. After editing:
#   systemctl --user restart scrap

# Image to run: a local build (podman build -t localhost/scrap:dev .)
# or a published one, e.g. ghcr.io/gilesknap/scrap:<version>.
SCRAP_IMAGE=localhost/scrap:dev

# How scrap is reached. socket: only a Unix socket, scrap.sock in
# \$XDG_RUNTIME_DIR/scrap, that this user and root (so Tailscale Serve) can
# open and other local users cannot. tcp: SCRAP_PORT on 127.0.0.1, which any
# local process can reach. Unset means tcp.
SCRAP_LISTEN=socket

# Port on 127.0.0.1 that scrap listens on when SCRAP_LISTEN=tcp.
SCRAP_PORT=8790

# Host directory for the database and files (mounted at /data).
SCRAP_DATA=$data/data

# Host directory for backups, and how many backup runs to keep (at least 1).
SCRAP_BACKUPS=$data/backups
SCRAP_BACKUP_KEEP=14

# Memory ceiling for the container (podman --memory syntax).
SCRAP_MEMORY_MAX=1g
ENV
    echo "Wrote $conf/env"
else
    echo "Keeping existing $conf/env"
fi
# setting KEY: KEY's value in the env file as systemd reads it: the last
# KEY= line, with surrounding whitespace and one pair of quotes removed.
setting() {
    sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$conf/env" 2>/dev/null |
        tail -n 1 | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' \
        -e "s/^'\\(.*\\)'$/\\1/"
}
sock="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/scrap/scrap.sock"
# An env file from before the socket has no SCRAP_LISTEN and stays on TCP:
# moving it would cut off whatever reaches scrap on the port today.
case $(setting SCRAP_LISTEN) in
socket) listen="the Unix socket $sock" target="unix:$sock" ;;
'' | tcp)
    port=$(setting SCRAP_PORT)
    port=${port:-8790} # as scrap-run
    listen="port $port on 127.0.0.1" target="http://127.0.0.1:$port"
    echo "Note: scrap listens on $listen, which any local user can reach." >&2
    echo "To serve it on a Unix socket only, set SCRAP_LISTEN=socket in" >&2
    echo "$conf/env, restart scrap and point Tailscale Serve at" >&2
    echo "unix:$sock (see the single-server deploy guide)." >&2
    ;;
*)
    echo "SCRAP_LISTEN in $conf/env must be socket or tcp." >&2
    exit 1
    ;;
esac

if [ -L "$conf/ingest.env" ] && [ ! -e "$conf/ingest.env" ]; then
    echo "Warning: $conf/ingest.env is a dangling symlink; not writing through it." >&2
elif [ ! -e "$conf/ingest.env" ]; then
    (
        umask 077
        cat >"$conf/ingest.env" <<'ENV'
# scrap's own settings, passed into the container by podman (--env-file).
# Mode 600: it holds the API key. Plain KEY=value lines, no quotes. The
# settings are listed in the API reference. After editing:
#   systemctl --user restart scrap

# Send photos to Claude (off by default; photos are queued either way).
#SCRAP_INGEST=on
#ANTHROPIC_API_KEY=
#SCRAP_VISION_MODEL=claude-opus-5-5
#SCRAP_BUDGET_DAY_USD=3

# Where a pause (budget, credit, auth, outage) is announced, e.g. an ntfy
# topic URL. Without it a pause goes unnoticed until you open scrap.
#SCRAP_NOTIFY_URL=
ENV
    )
    echo "Wrote $conf/ingest.env"
else
    echo "Keeping existing $conf/ingest.env"
    if [ -n "$(find -L "$conf/ingest.env" -perm /077)" ]; then
        echo "Warning: $conf/ingest.env is readable or writable by others: chmod 600 it." >&2
    fi
fi

# Remembered until scrap has (re)started on the new unit, even if this run
# stops before that.
pending="$lib/restart-pending"
cmp -s "$here/scrap.service" "$units/scrap.service" || : >"$pending"
cmp -s "$here/scrap-run" "$lib/scrap-run" || : >"$pending"
cp "$here/scrap-backup" "$here/scrap-gc" "$here/scrap-run" "$lib/"
cp "$here/scrap.service" "$here/scrap-backup.service" "$here/scrap-backup.timer" \
    "$here/scrap-gc.service" "$here/scrap-gc.timer" "$units/"
systemctl --user daemon-reload
if dropins=$(grep -ls '^ExecStart=' "$units"/scrap.service.d/*.conf); then
    echo "Note: a drop-in sets ExecStart, so scrap.service's own command is not used:" >&2
    echo "$dropins" >&2
fi

if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" != yes ]; then
    loginctl --no-ask-password enable-linger 2>/dev/null || {
        echo "Could not enable linger. As an admin run:" >&2
        echo "  sudo loginctl enable-linger $(id -un)" >&2
        echo "Without it scrap stops when $(id -un) logs out." >&2
    }
fi

image=$(setting SCRAP_IMAGE)
if ! podman image exists "$image"; then
    echo "Image $image is not here yet: build or pull it, then re-run this script." >&2
    exit 0
fi
# A running scrap keeps its old image and unit until restarted. A restart
# ends requests in flight; a photo being described counts one failed try
# and is retried later.
started=yes
case $(systemctl --user is-active scrap.service || true) in
active | activating | reloading)
    running=$(podman container inspect --format '{{.Image}}' scrap 2>/dev/null || true)
    if [ -e "$pending" ] ||
        [ "$running" != "$(podman image inspect --format '{{.Id}}' "$image")" ]; then
        echo "Restarting scrap onto the new image or unit."
        systemctl --user restart scrap.service || started=
    fi
    ;;
esac
[ -z "$started" ] || systemctl --user enable --now scrap.service || started=
if [ -n "$started" ]; then
    rm -f "$pending"
else
    echo "scrap did not start: journalctl --user -u scrap -n 50, and check" >&2
    echo "$conf/ingest.env and the image." >&2
fi
# The backup timer needs an image with the `scrap backup` command.
if podman run --rm "$image" backup --help >/dev/null 2>&1; then
    systemctl --user enable --now scrap-backup.timer
else
    systemctl --user disable --now scrap-backup.timer 2>/dev/null || true
    echo "Note: $image has no 'scrap backup' command, so the daily backup" >&2
    echo "timer is NOT enabled. Re-run this script after updating the image." >&2
fi
# The gc timer needs an image with the `scrap gc` command.
if podman run --rm "$image" gc --help >/dev/null 2>&1; then
    systemctl --user enable --now scrap-gc.timer
else
    systemctl --user disable --now scrap-gc.timer 2>/dev/null || true
    echo "Note: $image has no 'scrap gc' command, so the nightly gc" >&2
    echo "timer is NOT enabled. Re-run this script after updating the image." >&2
fi
[ -n "$started" ] || exit 1
echo "scrap is running on $listen: try $here/smoke.sh"
echo "Tailscale Serve proxies to $target (see the single-server deploy guide)."
