# Work on scrap with Claude

How changes to scrap are designed, built and shipped with Claude, in two sessions. The
details Claude follows are in the repo's skills: `.claude/skills/pr-cycle/` (the cycle),
`.claude/skills/sim/` (the design sim) and `.claude/skills/release/` (releasing). Claude
Code loads them in any session started in this repo.

## The two sessions

**The design session** is a Claude session in the cloud (few cores). It works out what to
build with you:

1. It reads the code, proposes options and mocks them in the **sim**: the real app built
   against a fake API and published as a private claude.ai artifact, so you can try it on
   your phone before any code ships. It checks its own screenshots at phone widths and at
   large text first.
2. When a question depends on your phone (what Chrome or an installed app does), it
   publishes a small throwaway test page to GitHub Pages for you to open, rather than
   guessing.
3. Once you have chosen, it puts a first cut on a branch, `design/<name>`, with only the
   fast checks run, pushes it and opens a **Handoff** issue: the goal, your decisions and
   what you turned down, what is on the branch, the remaining work as a checklist, and what
   "done" means in checkable terms.
4. It gives you one line to paste into the other session:

   ```text
   Run pr-cycle (workstation) for handoff issue #N, branch design/<name>.
   ```

Changes you ask for after the handoff go on the same branch, each added to the issue as a
comment, so the paste line stays the same.

**The workstation session** is a Claude Code session on your multi-core machine (usually
Remote Control). From the paste line it runs the cycle with subagents: implement, review
with a fresh pair of eyes, fix (up to three rounds), then the full checks as CI runs them,
including the end-to-end tests split across six parallel runs. Then it opens the PR (the
description lists what its own review found and fixed), deals with CI and CodeRabbit until
everything is green, and merges.

Releasing is separate: ask for a release, and the `release` skill tags, waits for the image
and chart, backs up and deploys.

## Habits worth keeping

- **Batch.** A cycle takes a while, so put the changes you already want into one handoff.
- **Better defaults over new settings.** Ask whether a default can be fixed before adding a
  setting.
- **One-off data changes are not code.** Something done once to your own data (such as
  moving old files into their pages' text) is written as a procedure and a throwaway script
  in the handoff issue: back up, dry run, apply as one undoable step, check. You run it after
  deploying.
- **Test on the phone.** The sim estimates large text and narrow screens; your phone is the
  final check, and a test page answers a device question in minutes.

## The sim

The sim's tooling is in `sim/` (see its `README.md`): build it from any checkout, serve and
screenshot it locally, and publish it to the sim artifact. It fakes the server in the
browser, so it shows designs, not server behaviour, and the artifact can't open file
pickers.
