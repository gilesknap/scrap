---
name: sim
description: "Build, check and publish scrap's design sim (the real PWA on a fake in-browser API, published as a claude.ai artifact), and put installable test copies of a branch on GitHub Pages for the owner's real phone. Use when designing or mocking a UI change, when asked for the sim, or when a bug or design depends on the real phone (text size, zoom, the installed app, restarts) and a release would be too slow."
---

# The design sim

The mechanics are in `sim/README.md`: read it before building. This is when and
how to use it in a design session (`.claude/skills/pr-cycle/`, Part A).

## Show designs in the sim

1. Build from the branch being designed: `npm --prefix web ci` once, then
   `sim/build.sh`, then `sim/serve.sh` for local screenshots.
2. If the design needs pages the fixtures lack, add a `# ---- <design> mock`
   block to `sim/mock.py`. If it needs an endpoint or a changed response, change
   `sim/sim.js` in the same branch (its endpoint table is in the README); the
   server isn't running, so the fake must answer what the new code asks.
3. **Look before you show.** Screenshot every screen the change touches with
   `sim/shots/shot.mjs` at 308, 320 and 390 px, 100 % and 130 % text, light and
   dark, and open the images yourself. The owner's phone is 308 CSS px wide at
   about 130 % text (a 22.1 px root), so that combination must look right.
   Use `sim/shots/sizes.mjs` when chip or control sizes are involved: they must
   match the type scale (`--t-sm` for chips), not just look plausible.
4. **Publish everything** to the sim artifact
   (https://claude.ai/artifact/PePhDjfGXhyk7jUAsXhbH5): the files map from
   `sim/files.py` (previous map as its argument, kept in the session scratchpad),
   `root` = `sim/out`, `file_path` = `sim/out/index.html`, no `capabilities`
   (the artifact keeps its `db`, for Feedback). Never publish only changed files:
   Vite re-splits chunks and a partial publish breaks the app.
5. Tell the owner the version number and what to try, screen by screen. He may
   be viewing an older version: if he reports something missing, check the
   build first, then suggest a reload.
6. Read his Feedback notes (ArtifactData `list`, collection `feedback`, the
   sim's url) when he says he left some.

What the sim can't show: server behaviour (saves, search ranking, ingest), file
pickers and the camera inside the artifact, and the installed app's own quirks.
Say so when a design depends on them, and put the check in the handoff.

## Test on the real phone (phone test copies)

The sim artifact runs inside the Claude app's viewer, not Chrome: no Chrome zoom, no install,
different text scaling. So it can look right while the installed app looks wrong (2026-10-28:
Chrome's 125–133 % zoom on top of the phone's font scale made the real app far bigger than the
sim). Whenever a problem or a design depends on the phone itself (text size, zoom, the
installed app, restarts, storage, the keyboard), don't wait for a release:

1. Build the branch into a test copy on GitHub Pages: `sim/phone.sh NAME` (see
   `sim/README.md`, "Phone test copies"). It is the sim, installable, with a yellow readout of
   the root size, the kept text size, `dpr`, width and installed/tab.
2. Test it locally first (serve a `gh-pages` checkout, run the steps with Playwright, a
   persistent profile for restarts); the cloud session can't fetch github.io.
3. Give the owner the link and exact steps: open in Chrome, install, what to do (pick, swipe
   away, reopen), and which readout values to send back.
4. `sim/phone.sh --delete NAME` once the question is settled.

For a question that isn't about scrap's own code (what Chrome or Android does at all), a tiny
static probe page in its own `gh-pages` folder does the same job (e.g. `textscale-test/`
showed that Android's font size reaches a page only with `<meta name="text-scale"
content="scale">`).
