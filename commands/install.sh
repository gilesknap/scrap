#!/bin/sh
# Install the scrap slash commands (the sc-*.md files beside this script) into
# ~/.claude/commands and the skill (skills/scrap-links in the repo) into
# ~/.claude/skills/scrap-links:
#   curl -fsSL https://github.com/gilesknap/scrap/releases/latest/download/install.sh | sh
# A scrap-to-gist skill installed by an earlier release (removed by ADR 43) is left alone.
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

echo "Installing the scrap commands from $ref into $dest and the scrap skills into $skills"
curl -fsSL "https://github.com/gilesknap/scrap/archive/$ref.tar.gz" |
    tar -xz -C "$tmp"
mkdir -p "$dest"
cp "$tmp"/*/commands/*.md "$dest"/
rm -f "$dest/sc-session.md"  # folded into /sc-summarise all
echo "Installed: $(cd "$tmp"/*/commands && echo *.md) -> $dest"
for name in scrap-links; do
    skill=$(echo "$tmp"/*/skills/$name)
    if [ -d "$skill" ]; then
        mkdir -p "$skills"
        rm -rf "${skills:?}/$name"
        cp -R "$skill" "$skills"/
        echo "Installed: $name skill -> $skills/$name"
    else
        echo "No $name skill in $ref: skipped"
    fi
done
echo "Start a new Claude Code session and type /sc."
