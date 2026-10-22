# 6. A vanilla TypeScript PWA with a size budget and lazy chunks

Date: 2026-10-19 (design system: 2026-10-19/20)

## Status

Accepted

## Context

The phone app opens from an icon, offline, one-handed. It also needs heavy pieces (an Excalidraw
editor, Markdown rendering, Mermaid) that must not slow that first screen. The project's goal is to
stay tiny: no UI framework, icon library or web font.

## Decision

- Vanilla TypeScript built by Vite into the Python package (`scrap/static`). React exists only
  inside the lazily loaded Excalidraw chunk.
- The app shell has a gzipped JavaScript **budget** (16 kB, raised from the original 15 kB), enforced
  by `npm run size` in CI. The service worker precaches the shell only; the lazy chunks it also
  keeps for offline use are those in `OFFLINE` in `web/vite.config.ts` (the composer, editor,
  page editor, Markdown renderer, sharing, search filters and recent searches), while Excalidraw
  (~405 kB gzipped), its fonts and Mermaid load only when used.
- The server gzips scripts, styles, pages and JSON, so the gzipped sizes are what crosses the wire.
- One design system, all tokens in `tokens.css`: paper and ink with a single amber accent, designed
  dark mode, controls under the thumb, every gesture also a button, icons always with words.
  Contrast is held to WCAG AA twice: a unit test over the tokens and an end-to-end sweep of real
  computed colours in both themes.
- A CSP (`font-src 'self' data:; connect-src 'self'`) keeps Excalidraw from reaching its CDN
  fallback.
- Pages open in a new tab as real links; swipes (row actions, paging) start away from the screen
  edges, which belong to the phone's Back gesture.

## Consequences

- New features usually mean a new lazy chunk, not growth of the shell.
- Accessibility regressions fail CI rather than review.
- No framework means some hand-written view plumbing; the trade was accepted for size and
  readability.
