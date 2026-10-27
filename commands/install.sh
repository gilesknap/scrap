#!/bin/sh
# Install the scrap slash commands (the sc-*.md files beside this script) into
# ~/.claude/commands and the scrap-links skill (skills/scrap-links in the repo) into
# ~/.claude/skills/scrap-links:
#   curl -fsSL https://github.com/gilesknap/scrap/releases/latest/download/install.sh | sh
# The copy attached to a release installs that release's files: the release job rewrites
# the default_ref line to its tag. Run from the repo, it installs main. SCRAP_REF=<tag|branch>
# overrides either. CLAUDE_COMMANDS_DIR and CLAUDE_SKILLS_DIR override the destinations.
set -eu

default_ref=main
ref="${SCRAP_REF:-$default_ref}"

dest="${CLAUDE_COMMANDS_DIR:-$HOME/.claude/commands}"
skills="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "Installing the scrap commands from $ref into $dest and the scrap-links skill into $skills"
curl -fsSL "https://github.com/gilesknap/scrap/archive/$ref.tar.gz" |
    tar -xz -C "$tmp"
mkdir -p "$dest"
cp "$tmp"/*/commands/*.md "$dest"/
rm -f "$dest/sc-session.md"  # folded into /sc-summarise all
mkdir -p "$skills"
rm -rf "$skills/scrap-links"
cp -R "$tmp"/*/skills/scrap-links "$skills"/
echo "Installed: $(cd "$tmp"/*/commands && echo *.md) -> $dest"
echo "Installed: scrap-links skill -> $skills/scrap-links"
echo "Start a new Claude Code session and type /sc."
