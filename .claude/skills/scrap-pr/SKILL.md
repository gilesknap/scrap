---
name: scrap-pr
description: "scrap's specifics for designing, handing off and shipping a change: the full local checks (tox, web, the six e2e shards), the 16.5 kB app-shell budget, the owner's phone, the sim, migrations, git over HTTPS, and the cloud design / workstation handoff. Use it for any PR in this repo, alongside the user pr-cycle skill, which has the process (subagents, review rounds, CI, merge); this skill adds scrap's details on top and wins where they differ."
---

# scrap-pr

The process is the user `pr-cycle` skill: subagents implement, a fresh
reviewer each round, fix rounds (6 at most), "Found in local review", CI and
CodeRabbit (advisory), and the main thread merges when green with the
owner's permission. Load `pr-cycle` too if it isn't loaded, and follow it
with these scrap specifics. The overview for people is
`docs/how-to/work-with-claude.md`.

## The owner and the UI

- **The owner decides design.** Any visible change (the PWA, or the public
  site's look) is mocked first and the owner OKs screenshots (CLAUDE.md).
- **Prefer fixing defaults over adding settings.** The UI is calm: one amber
  hero, small chips, less is more.
- **The owner's phone:** Android, 308 CSS px wide, about 130 % text.
- **The mock tool is the sim** (the `sim` skill, `.claude/skills/sim/`): the
  real PWA on a fake API, published to the sim artifact. Screenshot at 308,
  320 and 390 px, 100 % and 130 % text, light and dark. For a question about
  the real phone (zoom, the installed app, restarts), publish a test copy
  with `sim/phone.sh NAME` rather than wait for a release. For the public
  site, a static page from `web/src/public/page.css` is enough.
- **Batch.** A cycle is long, so gather the changes the owner already wants
  into one PR or handoff.

## Two sessions (the handoff, short form)

Decide which session you are; if unsure, ask.

- **Design session**: a cloud container (`nproc` under 8), or the owner says
  "design" or "hand off". The cloud may not have the user `pr-cycle` skill,
  so this is complete on its own. Design in the sim; a subagent puts a first
  cut on `design/<slug>` with only the fast checks (never the full e2e suite
  on few cores); push, check with `git ls-remote`, don't open a PR. Open a
  "Handoff: <change>" issue: the goal and chosen design in words, with the
  sim version; decisions and what the owner turned down; what is on the
  branch (commits, files, server contracts, checks run); remaining work as a
  checklist, with the e2e specs at risk; "Done when" in checkable terms
  (sizes, widths, what must never clip or wrap); risks and open questions;
  the merge instruction and the release it is wanted for. Reply with:
  `Run scrap-pr (workstation) for handoff issue #N, branch design/<slug>.`
  Later changes: push to the same branch and comment "Added after the
  handoff (owner, date): ..."; a replacing comment says "Supersedes ...".
- **Handing off an open PR** (rare): stop subagents at a safe point, commit
  "WIP: handoff" saying which checks pass, push, comment on the PR (last
  green commit, failing checks with log links, suspected causes, open
  threads, merge instruction), and paste
  `Run scrap-pr (workstation) for PR #N, branch <branch>; the handoff is in its latest comment.`
- **Workstation session**: the owner's multi-core machine (usually Remote
  Control). Read the issue and all its comments, work in a worktree, merge
  `origin/main` in if it moved, and run the cycle. A visual fix found here
  goes back to the sim for a mock. Most work now starts and ends here.

## Full local checks (the same as CI, before any push)

- Python: `uv run tox -p` (pre-commit, pyright, pytest, docs).
- Web: `npm --prefix web run check`, `npm --prefix web test`,
  `npm --prefix web run build`, `npm --prefix web run size` (the app shell
  within **16.5 kB** gzipped).
- e2e, in full once by the implementer (reviewers and fix rounds run only
  the affected specs), as CI splits it: six shards at once, each on its own
  port base from `web/e2e/ports.ts` (scrap on the base, the receiver on
  +100, the site on +200), with `SCRAP_MCP_TOKEN` and `SCRAP_CF_*` unset:
  `env -u SCRAP_MCP_TOKEN -u SCRAP_CF_ID -u SCRAP_CF_SECRET
  SCRAP_E2E_PORT=$((8790+i)) npm --prefix web run e2e -- --shard=$i/6` for
  i in 1..6 (fewer at a time if cores are short). A second checkout side by
  side uses `8800+i`. A failure only
  under load: rerun it alone, then fix the race; never retry until it passes.
- Migrations, if any: `CLAUDE.md` (`--snapshot`). They are numbered by merge
  order and never reserved, unlike pr-cycle's "reserve shared numbers".

## Git and GitHub

- **HTTPS only**, never SSH, on every fetch, push and clone: `GIT_CONFIG_GLOBAL=/dev/null git -c
  credential.helper='!gh auth git-credential' <cmd>
  https://github.com/gilesknap/scrap.git ...` (a global `insteadOf` rewrites
  plain `origin` to SSH). Check every push with `git ls-remote` in the same
  form. A stale remote-tracking ref (e.g. `refs/remotes/origin/design`) can
  block pushes or fake "unpushed commits" warnings: `git update-ref -d` it.
- **GraphQL may be blocked**: use REST, e.g.
  `gh api repos/gilesknap/scrap/issues -f title=... -F body=@file`.
- Releasing is the `release` skill (it backs up before deploying).

## Data changes are not code

A one-off change to the owner's data (moving files into page text, retyping
old pages) never goes in scrap's code. Write it as a procedure plus a
throwaway script in the issue (a comment): back up, dry run with a
before/after table, apply in one transaction or one revertable batch, check,
and how to undo. The workstation tests it on a copy of real data; the owner
runs it after deploying, and the one-line merge report to him names it.
