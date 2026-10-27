#!/bin/sh
# Install the scrap slash commands (the sc-*.md files beside this script) into
# ~/.claude/commands:
#   curl -fsSL https://github.com/gilesknap/scrap/releases/latest/download/install.sh | sh
# The copy attached to a release installs that release's commands: the release job rewrites
# the default_ref line to its tag. Run from the repo, it installs main. SCRAP_REF=<tag|branch>
# overrides either.
set -eu

default_ref=main
ref="${SCRAP_REF:-$default_ref}"

dest="${CLAUDE_COMMANDS_DIR:-$HOME/.claude/commands}"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "Installing the scrap commands from $ref into $dest"
curl -fsSL "https://github.com/gilesknap/scrap/archive/$ref.tar.gz" |
    tar -xz -C "$tmp"
mkdir -p "$dest"
cp "$tmp"/*/commands/*.md "$dest"/
rm -f "$dest/sc-session.md"  # folded into /sc-summarise all
echo "Installed: $(cd "$tmp"/*/commands && echo *.md) -> $dest"
echo "Start a new Claude Code session and type /sc."
