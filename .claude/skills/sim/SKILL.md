---
name: sim
description: "Build, check and publish scrap's design sim (the real PWA on a fake in-browser API, published as a claude.ai artifact the owner opens on his phone), and probe the owner's phone with throwaway test pages. Use when designing or mocking a UI change, when asked for the sim or to publish it, or when a design question depends on the phone."
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

## Probe the phone

When the answer depends on the owner's real phone (what Chrome, Android or the
installed app does: text size, zoom, the keyboard, install behaviour), measure
it instead of guessing:

1. Write a tiny static page that prints the numbers in question live (refresh
   every second), with a manifest, icons and a pass-through service worker if it
   must be installable. Make variants side by side (with and without the thing
   being tested) with a link between them.
2. Publish it as its own folder on the `gh-pages` branch of gilesknap/scrap
   (clone `-b gh-pages --depth 1`, add the folder, push). It serves at
   `https://gilesknap.github.io/scrap/<folder>/` over HTTPS within a minute or
   two; the docs deploy uses `keep_files`, so it survives. The cloud session
   can't fetch it to check: ask the owner.
3. Give the owner exact steps (in a Chrome tab, then installed) and exactly
   which numbers to send back.
4. Delete the folder when the question is settled.

Example: `textscale-test/` showed that Android's font size reaches neither a
Chrome tab nor the installed app without `<meta name="text-scale"
content="scale">`, and reaches both with it.
