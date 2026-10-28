---
name: pr-cycle
description: "scrap's way to ship a change, in two sessions: a cloud design session designs (with the sim), pushes a design branch and opens a Handoff issue; the owner's workstation session implements, reviews and fixes with subagents, runs the full checks, opens the PR, fixes CI and CodeRabbit and merges. Use when asked to design, hand off, make a PR, ship a change or run the PR cycle in this repo. For scrap, use this rather than a general pr-cycle skill."
---

# PR cycle (scrap)

Two sessions share the work. Decide which one you are:

- **Design session**: a cloud container with few cores (`nproc` under 8), or the
  owner says "design" or "hand off". Do Part A.
- **Workstation session**: the owner's multi-core machine (usually a Remote
  Control session), handed a handoff issue, a branch or a PR. Do Part B.

If unsure, ask. In both roles you orchestrate and subagents do the heavy work;
keep your own context for decisions and for talking to the owner. The overview
for people is `docs/how-to/work-with-claude.md`.

## Ground rules (both sessions)

- **Batch.** A cycle is long (design, handoff, review, CI, release), so gather
  the changes the owner already wants into one handoff rather than one each.
- **The owner decides design.** Mock it, show it, let him choose. A visual fix
  found during Part B goes back to a design session for a mock.
- **Prefer fixing defaults over adding settings.** The UI is calm: one amber
  hero, small chips, less is more. The owner uses Android at about 130 % text
  on a screen 308 CSS px wide.
- **Check pushes against GitHub**, not local warnings: `git ls-remote origin
  <branch>` must show the commit you pushed. A checkout may lose its
  remote-tracking refs (a stale `refs/remotes/origin/design` once blocked every
  `design/...` branch; `git update-ref -d` it), so "unpushed commits" hooks can
  be false alarms.
- **GraphQL may be blocked**: use REST, e.g.
  `gh api repos/gilesknap/scrap/issues -f title=... -F body=@file`.
- **Attribution**: end commits and PR bodies with the attribution lines the
  session gives you.
- **Data changes are not code.** A one-off change to the owner's data (moving
  files into page text, retyping old pages) never goes in scrap's code. Write it
  as a procedure plus a throwaway script in the handoff issue (a comment): back
  up, dry run with a before/after table, apply in one transaction or one
  revertable batch, check, and how to undo. Part B tests it on a copy of real
  data; the owner runs it after deploying.

## Part A: design session (cloud)

1. **Design.** Read the code involved first. Work out options and mock them in
   the sim (`.claude/skills/sim/`): the real app on a fake API, published to the
   sim artifact for the owner's phone. Screenshot your own work at 308, 320 and
   390 px, 100 % and 130 % text, light and dark, and look at every shot before
   showing it. Ask the owner only real choices (AskUserQuestion, recommended
   option first).
2. **Answer device questions on the device.** When the answer depends on the
   owner's phone (what the browser or an installed app does), don't guess:
   publish a throwaway probe page to the `gh-pages` branch under a folder of its
   own (it serves at `https://gilesknap.github.io/scrap/<folder>/`, HTTPS, so
   it can be installed as an app; the docs deploy keeps other files), have the
   owner read its numbers, then delete the folder.
3. **First cut.** On a new branch off `origin/main`, `design/<slug>`: the code,
   tests and docs you are confident of, usually by a subagent with a full brief.
   Run only the fast checks (below). Never the full e2e suite here: it is slow
   on few cores and flaky under load. Single specs you touched are fine.
4. **Push** the branch and confirm it with `git ls-remote`. Don't open a PR.
5. **Handoff issue**, titled "Handoff: <change>", with:
   - the goal and the chosen design, and a link to the sim (version number);
   - decisions and why, and what the owner turned down;
   - what is on the branch: commits, files, server contracts, checks run;
   - remaining work as a checklist, including the e2e specs at risk;
   - "Done when" in checkable terms (sizes, widths, positions, what must never
     clip or wrap), with the design in words, since Part B may not open the sim;
   - risks and open questions;
   - the merge instruction (squash unless said otherwise), and the release it
     is wanted for.
6. **Reply** with the one line for the owner to paste into the workstation:
   `Run pr-cycle (workstation) for handoff issue #N, branch design/<slug>.`

**Changes after the handoff** (before Part B starts, or while it runs): commit
and push to the same branch, then comment on the issue: "Added after the
handoff (owner, date): ..." with the commit, what changed, and new checklist
items. A comment that replaces an earlier one says "Supersedes ...". The paste
line stays the same.

**Handing off an open PR** (rare: a small change taken to a PR here that needs
more rounds than this machine handles): stop subagents at a safe point, commit
"WIP: handoff" saying which checks pass, push, and comment on the PR with the
last green commit, failing checks with log links, suspected causes, open review
threads and the merge instruction. Paste line:
`Run pr-cycle (workstation) for PR #N, branch <branch>; the handoff is in its latest comment.`

## Part B: workstation session

0. Read the handoff issue and **all its comments** (later ones add to or
   supersede the body), check out the branch, merge `origin/main` in if it
   moved, and read `CLAUDE.md` and `.github/CONTRIBUTING.md`. Ask the owner
   only about real gaps.
1. **Implement** (subagent): the handoff's goal, decisions, checklist,
   conventions and checks. It commits on the branch; it does not push.
2. **Review** (a fresh subagent): it gets the handoff and the diff
   (`git diff origin/main...HEAD`), not the implementer's reasoning. It may run
   targeted specs and probes. Findings ranked by severity, each with file, line
   and a concrete failure, marked confirmed or plausible.
3. **Fix** (subagent, continuing the implementer): keep a list, one line per
   issue and its fix. Repeat review and fix until nothing significant is left,
   three rounds at most, then tell the owner what remains. A fix that needs a
   design choice goes to the owner; a visual one, back to a design session.
4. **Full local checks**, the same as CI, before any push:
   - Python: `uv run tox -p` (pre-commit, pyright, pytest, docs).
   - Web: `npm --prefix web run check`, `npm --prefix web test`,
     `npm --prefix web run build`, `npm --prefix web run size` (app shell
     within 16.5 kB gzipped).
   - e2e, split as CI splits it, the shards in parallel, each on its own port
     and data folder: `SCRAP_E2E_PORT=$((8790+i)) npm --prefix web run e2e --
     --shard=$i/6` for i in 1..6 at once (fewer at a time if the cores are
     short). A failure only under load: rerun it alone, then fix the race in the
     test or the app; never retry until it passes.
   - Migrations, if any: `CLAUDE.md` (number, `--snapshot`).
   - A one-off data script from the handoff: run it on a copy of real data.
5. **Open the PR** (subagent): push, PR against main. The body has what changed
   and why with "Closes #<handoff issue>", how it was tested, "Found in local
   review" (one line per issue and fix, from step 3), "Not in this PR", and the
   merge instruction.
6. **CI and CodeRabbit**: watch both; fix real issues on the branch (rerun the
   affected specs locally first); answer comments that don't apply with a
   one-line reason and resolve them. If main moved and the PR conflicts, merge
   main in. Repeat until every check is green, the PR is mergeable and no
   thread is open.
7. **Merge when green**, squash unless the handoff says otherwise. Tell the
   owner in one line with the PR number, and any one-off data procedure he now
   needs to run. Releasing is the `release` skill. If a push, tag or merge is
   blocked by the environment, say so and stop; don't work around it.
