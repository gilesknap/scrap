(auto-summary-on-compact)=

# Post a summary to scrap when Claude Code compacts

When Claude Code compacts a long session, the detail of the earlier part is lost, so a
`/sc-summarise all` written afterwards can only work from the compaction summary. The
`PreCompact` hook in `hooks/scrap-precompact.py` posts a summary to scrap just before each
compaction, while the whole transcript is still there.

## What it does

- Runs on the `PreCompact` event. It reads the session id and `transcript_path` from the hook
  input, and turns the transcript into plain dialogue: your messages and Claude's replies, with
  tool calls and tool output left out.
- Runs `claude -p` headless over that dialogue. It may use only `mcp__scrap__tags`, `search`,
  `read` and `write`.
- Writes **one page per Claude session**. The first compaction creates it, titled
  `[auto-compact] <topic>`, tagged `scrap` and `auto-compact` plus topic tags, with the working
  directory and date as origin. Later compactions of the same session append a section,
  `## Compaction N (date)`, covering only what happened since the last one.
- Keeps a small map of session id to page slug (and how far into the transcript it has
  summarised) in `$XDG_STATE_HOME/scrap/precompact.json` (`~/.local/state/scrap/precompact.json`).
  Delete the file, or a session's entry, to make the next compaction start a new page.
- Never blocks compaction: on any error (no network, scrap down, `claude` missing, a timeout) it
  logs to stderr and exits 0. `SCRAP_PRECOMPACT_TIMEOUT` (seconds, default 180) bounds the model
  call.
- The prompt follows `/sc-summarise all` (timeline, findings, decisions, changes made, open
  questions) and tells the model to leave out secrets, tokens, credentials and raw tool output.
  Check the page rather than trusting that: the model does the redaction.

It costs one extra model call per compaction.

## Install

1. Connect Claude Code to scrap as in [](connect-claude-code.md) (the `claude mcp add` line, user
   scope, so the headless call sees it).
2. Copy `hooks/scrap-precompact.py` somewhere stable (for example `~/.claude/hooks/`), keeping it
   executable. It needs only Python 3.
3. Add the hook to `~/.claude/settings.json` (all projects) or `.claude/settings.json` (one
   project):

   ```json
   {
     "hooks": {
       "PreCompact": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "python3 ~/.claude/hooks/scrap-precompact.py",
               "timeout": 200
             }
           ]
         }
       ]
     }
   }
   ```

The headless call runs with `--allowedTools` limited to the four scrap tools and
`--permission-mode dontAsk`, so it asks for nothing and can do nothing else. It does need your
Claude Code login and the scrap server to be reachable.

## Try it without compacting

Pipe a hook input made from a real transcript to the script (this does post a page):

```sh
t=$(ls -t ~/.claude/projects/*/*.jsonl | head -1)
printf '{"session_id":"test-1","transcript_path":"%s","cwd":"%s"}' "$t" "$PWD" |
  python3 hooks/scrap-precompact.py
```

Run it twice with more conversation in between to see the second run append. Remove the
`test-1` entry from the state file afterwards.

## Turn it off

Remove the `PreCompact` entry from `settings.json`, or set `SCRAP_PRECOMPACT_RUNNING=1` in the
environment of the session. Pages already posted stay; they carry the `auto-compact` tag
(`tag:auto-compact`), so `/sc-tidy` can retag or you can delete them in the app.
