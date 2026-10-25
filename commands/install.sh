#!/bin/sh
# Install the scrap slash commands (the sc-*.md files beside this script) into
# ~/.claude/commands:  curl -fsSL https://raw.githubusercontent.com/gilesknap/scrap/main/commands/install.sh | sh
set -eu

dest="${CLAUDE_COMMANDS_DIR:-$HOME/.claude/commands}"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

curl -fsSL https://github.com/gilesknap/scrap/archive/refs/heads/main.tar.gz |
    tar -xz -C "$tmp"
mkdir -p "$dest"
cp "$tmp"/*/commands/*.md "$dest"/
rm -f "$dest/sc-session.md"  # folded into /sc-summarise all
echo "Installed: $(cd "$tmp"/*/commands && echo *.md) -> $dest"
echo "Start a new Claude Code session and type /sc."
