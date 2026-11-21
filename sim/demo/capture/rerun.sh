#!/usr/bin/env bash
# Rerun the demo-video capture (#549) from scratch: a throwaway scrap on 8765, seeded
# with the sim's demo pages, then three claude -p steps in one resumed session.
# Only the local server is reachable: --strict-mcp-config with seed/demo-mcp.json.
set -euo pipefail
CAP=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)   # sim/demo/capture: the scripts and seed
REPO=$(cd "$CAP/../../.." && pwd)
TR=$REPO/sim/demo/transcript   # what the recorder reads (build_transcript.py writes it)
cd "$REPO"
OUT=$REPO/_claude/demo-video   # the raw runs and API dumps (gitignored)
mkdir -p "$OUT"
DEMO=$HOME/demo   # neutral cwd for the claude -p steps: empty, no CLAUDE.md
mkdir -p "$DEMO"
DATA=$(mktemp -d)/demo-data
export UV_PYTHON=3.13   # this sandbox has 3.13 only; drop elsewhere

SCRAP_INGEST=off SCRAP_PUBLIC_URL=https://scrap.example.com \
  uv run scrap serve --data-dir "$DATA" --port 8765 > "$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER' EXIT
until curl -sf --noproxy '*' 'http://127.0.0.1:8765/api/pages?limit=1' >/dev/null; do sleep 1; done

uv run python -I "$CAP/seed/seed_demo.py" http://127.0.0.1:8765 > "$OUT/ids.json"
uv run python "$CAP/seed/post_seed.py" "$DATA"

MCP=(--strict-mcp-config --mcp-config "$CAP/seed/demo-mcp.json"
     --allowedTools mcp__scrap__search,mcp__scrap__read,mcp__scrap__tags,mcp__scrap__topics,mcp__scrap__write
     --output-format stream-json --verbose)
# verify first: only the local scrap must be connected, and it must return demo pages
(cd "$DEMO" && claude -p "Use the scrap search tool with the query 'whiteboard' and list the titles it returns. Nothing else." \
  --strict-mcp-config --mcp-config "$CAP/seed/demo-mcp.json" --allowedTools mcp__scrap__search \
  --output-format stream-json --verbose) > "$OUT/00-verify.jsonl"
jq -c 'select(.type=="system" and .subtype=="init") | .mcp_servers' "$OUT/00-verify.jsonl"
jq -r 'select(.type=="result") | .result' "$OUT/00-verify.jsonl"
read -rp "Only scrap (dynamic) and demo pages above? Enter to go on, Ctrl-C to stop. "

cd "$DEMO"
SID=$(cat /proc/sys/kernel/random/uuid); echo "$SID" > "$OUT/session-id.txt"
claude -p "/sc-find whiteboard" --session-id "$SID" "${MCP[@]}" > "$OUT/01-find.jsonl"
claude -p "/sc-answer what's on my plate at home this week?" --resume "$SID" "${MCP[@]}" > "$OUT/02-answer.jsonl"
claude -p "/sc-write this weekend's house jobs as one todo checklist, most urgent first. Just post." \
  --resume "$SID" "${MCP[@]}" > "$OUT/03-write.jsonl"

# the committed take's step b (/sc-answer) was the second of two tries, run on a copy of the
# session cut after step a
cd "$REPO"
ID=$(curl -s --noproxy '*' 'http://127.0.0.1:8765/api/pages?limit=1' | jq -r '.[0].id')
curl -s --noproxy '*' "http://127.0.0.1:8765/api/pages/$ID" > "$OUT/written-page-api.json"

# ---- segment 2 (#549): a small fix in a toy repo, a house-jobs check, /sc-summarise, then
# /sc-summarise day with two staged peer sessions. Everything here runs under the demo's own
# Claude config (seed/demo-env.sh: env -i, CLAUDE_CONFIG_DIR=/root/demo-claude, the real binary),
# so ListAgents sees only demo sessions and no owner CLAUDE.md reaches the transcript.
DC=/root/demo-claude; CL="$CAP/seed/demo-env.sh"
mkdir -p "$DC/commands" "$DC/skills"
ln -sf /root/.claude/.credentials.json "$DC/.credentials.json"   # shared auth, nothing else
cp /root/.claude/commands/sc*.md "$DC/commands/"; cp -r /root/.claude/skills/scrap-links "$DC/skills/"
# /root/.claude/CLAUDE.md is picked up as a *project* file for any cwd under /root: exclude it
echo '{"permissions":{"allow":[]},"claudeMdExcludes":["/root/.claude/CLAUDE.md","/root/.claude/**"]}' > "$DC/settings.json"
"$CL" -p hi --strict-mcp-config --mcp-config "$CAP/seed/demo-mcp.json" >/dev/null   # makes .claude.json
TIDY=$DEMO/tidy
rm -rf "$TIDY" "$DEMO/tidy-readme" && mkdir -p "$TIDY" && tar xf "$CAP/seed/tidy-initial.tar" -C "$TIDY"
jq '.projects = ((.projects // {}) + ({"/root/demo":{}, "/root/demo/tidy":{}, "/root/demo/tidy-readme":{}}
   | map_values({hasTrustDialogAccepted: true, hasCompletedProjectOnboarding: true})))' "$DC/.claude.json" > "$DC/.claude.json.tmp"
cat "$DC/.claude.json.tmp" > "$DC/.claude.json"; rm "$DC/.claude.json.tmp"
cd "$TIDY"
git init -q -b main && git config user.name "Alex Demo" && git config user.email alex@example.com
git add -A && GIT_AUTHOR_DATE="2026-11-14T10:12:00" GIT_COMMITTER_DATE="2026-11-14T10:12:00" \
  git commit -qm "tidy: rename files to clean names"
git worktree add -q ../tidy-readme -b readme-usage main
(unset UV_PROJECT_ENVIRONMENT VIRTUAL_ENV; UV_LINK_MODE=copy uv run pytest -q)
# memory check: the isolated session must load no CLAUDE.md (no "instructions" attachment)
"$CL" -p "Reply with the single word: ready" --permission-mode dontAsk --strict-mcp-config \
  --mcp-config "$CAP/seed/demo-mcp.json" --output-format stream-json --verbose > "$OUT/04a-verify-memory.jsonl"
S=$(jq -r 'select(.type=="system" and .subtype=="init") | .session_id' "$OUT/04a-verify-memory.jsonl")
if grep -q '"type":"instructions"' "$DC/projects/-root-demo-tidy/$S.jsonl"; then echo "a CLAUDE.md was loaded: stop"; exit 1; fi
MCPD=(--permission-mode dontAsk --strict-mcp-config --mcp-config "$CAP/seed/demo-mcp.json")
SEG2=("${MCPD[@]}" --allowedTools 'Read,Edit,Write,Glob,Grep,Bash(git status:*),Bash(git diff:*),Bash(git log:*),Bash(git branch:*),Bash(git switch:*),Bash(git checkout:*),Bash(git add:*),Bash(git commit:*),Bash(uv run pytest:*),mcp__scrap__search,mcp__scrap__read,mcp__scrap__tags,mcp__scrap__write'
      --disallowedTools 'Bash(git push:*),Bash(gh:*)' --output-format stream-json --verbose)
DAY=("${MCPD[@]}" --allowedTools 'Read,Glob,Grep,Bash(git status:*),Bash(git diff:*),Bash(git log:*),Bash(git branch:*),Bash(gh api:*),Bash(gh pr list:*),Bash(gh issue list:*),Bash(jq:*),ListAgents,SendMessage,mcp__scrap__search,mcp__scrap__read,mcp__scrap__tags,mcp__scrap__write,mcp__scrap__revisions,mcp__scrap__topics'
     --disallowedTools 'Bash(git push:*)' --output-format stream-json --verbose)
"$CL" -p "Use the scrap search tool with the query 'whiteboard' and list the titles it returns. Nothing else." \
  "${MCPD[@]}" --allowedTools mcp__scrap__search --output-format stream-json --verbose > "$OUT/04-verify.jsonl"
jq -c 'select(.type=="system" and .subtype=="init") | [.cwd, .permissionMode, .mcp_servers]' "$OUT/04-verify.jsonl"
read -rp "Only scrap (dynamic)? Enter to go on, Ctrl-C to stop. "
SID2=$(cat /proc/sys/kernel/random/uuid); echo "$SID2" > "$OUT/session-id.tidy-day.txt"
"$CL" -p "Fix the issue in ISSUE.md on a branch, run the tests, and commit." --session-id "$SID2" "${SEG2[@]}" > "$OUT/05-fix.jsonl"
"$CL" -p "Different thing: what's left on this weekend's house jobs?" --resume "$SID2" "${SEG2[@]}" > "$OUT/06-housejobs.jsonl"
"$CL" -p "/sc-summarise" --resume "$SID2" "${SEG2[@]}" > "$OUT/07-summarise.jsonl"   # it asks before posting
"$CL" -p "yes" --resume "$SID2" "${SEG2[@]}" > "$OUT/08-post.jsonl"
# two live peer sessions (background, so ListAgents finds them and they can reply); the prompt
# must come before --allowedTools, which would swallow it
(cd "$DEMO/tidy-readme" && "$CL" --bg "Tidy up README.md: add a short Usage section that shows a dry run first (tidy.py <folder> --dry-run, then without it), and commit on this branch. The --dry-run bug itself is being fixed on the fix-dry-run branch, so just do the README here." \
  -n tidy-readme "${MCPD[@]}" --allowedTools 'Read,Edit,Write,Glob,Grep,Bash(git status:*),Bash(git diff:*),Bash(git log:*),Bash(git add:*),Bash(git commit:*),ListAgents,SendMessage')
(cd "$DEMO" && "$CL" --bg "Save a short note to scrap for the camping trip: still to pack are the stove and gas, head torches and the first aid kit; buy gas canisters at the outdoor shop on Saturday morning. Link the camping kit page. Just post." \
  -n camping "${MCPD[@]}" --allowedTools 'mcp__scrap__search,mcp__scrap__read,mcp__scrap__tags,mcp__scrap__write,ListAgents,SendMessage')
until [ "$("$CL" agents --json | jq -r '[.[].state] | join(",")')" = "done,done" ]; do sleep 5; done
# isolation check: ListAgents and nothing else must list only the two demo sessions
"$CL" -p "Call the ListAgents tool once and report exactly what it returns. Do nothing else." \
  "${MCPD[@]}" --allowedTools ListAgents --output-format stream-json --verbose > "$OUT/12-verify-listagents.jsonl"
jq -r 'select(.type=="result") | .result' "$OUT/12-verify-listagents.jsonl"
read -rp "Only tidy-readme and camping listed? Enter to go on, Ctrl-C to stop. "
"$CL" -p "/sc-summarise day" --resume "$SID2" "${DAY[@]}" > "$OUT/09-summarise-day.jsonl"
"$CL" -p "yes" --resume "$SID2" "${DAY[@]}" > "$OUT/10-post-day.jsonl"
cp "$DC/projects/-root-demo-tidy/$SID2.jsonl" "$OUT/09-session-day.jsonl"
UV_PYTHON=3.13 uv run --no-project python -I "$CAP/seed/peer_replies.py" "$OUT/09-session-day.jsonl" "$TR/peer-replies.json"
for id in $("$CL" agents --json | jq -r '.[].id'); do "$CL" stop "$id"; done
page() { curl -s --noproxy '*' "http://127.0.0.1:8765/api/pages/$(curl -s --noproxy '*' 'http://127.0.0.1:8765/api/pages?limit=10' | jq -r --arg s "$1" '.[] | select(.slug==$s) | .id')"; }
page house-jobs-this-weekend-2122-nov-2026 > "$OUT/summary-page-api.json"
page "$(jq -r 'select(.type=="user") | .message.content[]? | select(.type=="tool_result") | .content | select(type=="string")' "$OUT/10-post-day.jsonl" | jq -r 'select(.created) | .slug')" > "$OUT/summary-day-page-api.json"
cd "$REPO" && UV_PYTHON=3.13 uv run --no-project python -I "$CAP/build_transcript.py" "$OUT" "$TR"
