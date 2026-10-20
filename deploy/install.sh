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

# Port on 127.0.0.1 that scrap listens on. Only local processes can reach it.
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

if [ ! -e "$conf/ingest.env" ]; then
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
    if [ -n "$(find "$conf/ingest.env" -perm /077)" ]; then
        echo "Warning: $conf/ingest.env is readable by others: chmod 600 it." >&2
    fi
fi

unit_changed=
cmp -s "$here/scrap.service" "$units/scrap.service" || unit_changed=1
cp "$here/scrap-backup" "$lib/"
cp "$here/scrap.service" "$here/scrap-backup.service" "$here/scrap-backup.timer" "$units/"
systemctl --user daemon-reload

if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" != yes ]; then
    loginctl --no-ask-password enable-linger 2>/dev/null || {
        echo "Could not enable linger. As an admin run:" >&2
        echo "  sudo loginctl enable-linger $(id -un)" >&2
        echo "Without it scrap stops when $(id -un) logs out." >&2
    }
fi

image=$(sed -n 's/^SCRAP_IMAGE=//p' "$conf/env")
if ! podman image exists "$image"; then
    echo "Image $image is not here yet: build or pull it, then re-run this script." >&2
    exit 0
fi
# A running scrap keeps its old image and unit until restarted. A restart
# ends requests in flight; a photo being described counts one failed try
# and is retried later.
if systemctl --user is-active --quiet scrap.service; then
    running=$(podman container inspect --format '{{.Image}}' scrap 2>/dev/null || true)
    if [ -n "$unit_changed" ] ||
        [ "$running" != "$(podman image inspect --format '{{.Id}}' "$image")" ]; then
        echo "Restarting scrap onto the new image or unit."
        systemctl --user restart scrap.service
    fi
fi
systemctl --user enable --now scrap.service
# The backup timer needs an image with the `scrap backup` command.
if podman run --rm "$image" backup --help >/dev/null 2>&1; then
    systemctl --user enable --now scrap-backup.timer
else
    systemctl --user disable --now scrap-backup.timer 2>/dev/null || true
    echo "Note: $image has no 'scrap backup' command, so the daily backup" >&2
    echo "timer is NOT enabled. Re-run this script after updating the image." >&2
fi
echo "scrap is running: try $here/smoke.sh"
