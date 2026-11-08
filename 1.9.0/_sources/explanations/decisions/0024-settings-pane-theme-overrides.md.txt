# 24. A settings pane in the top bar, with theme overrides

Date: 2026-10-23

## Status

Accepted

## Context

Colour followed `prefers-color-scheme` alone. A phone set to dark made every drawing dark too,
yet a drawing sits beside a photo of a whiteboard or paper, which is light: the pair looks
better with the drawing light. Nothing in the app held a user setting.

## Decision

- **A cog at the right end of the top bar**, on every screen, opens a small sheet (like the
  editor's: focus kept inside, Escape and Done close it, Back too).
- **Two settings, kept in `localStorage`** through `kept()` (they are per device, need no
  server and must work offline): the app theme (System by default, Light, Dark) and the
  drawings' theme (Light by default, Dark, Same as app).
- **One module, `web/src/theme.ts`,** resolves both from the choice and the OS setting and is
  used by the drawing previews, the full-screen viewer and Mermaid. A change applies at once:
  previews are drawn again (their cache key holds the theme), an open viewer renders with the
  new Excalidraw theme, and the OS changing is followed while a choice says "system".
- **The app theme is `data-theme` on `<html>`.** `tokens.css` keeps the dark values twice (in
  the media query for System, unless Light is chosen, and under `[data-theme="dark"]`), as CSS
  has no way to share them. `color-scheme` and the `theme-color` metas follow. A small inline
  script in `index.html` sets the attribute before first paint, so a chosen theme does not
  flash; the page's CSP does not restrict scripts.
- **Drawings default to Light**, whatever the OS says. Exports are unchanged (white).

## Consequences

- A phone in dark mode now shows light drawings until the user changes it.
- Mermaid diagrams take the app theme when drawn; one already on a page keeps its colours
  until the page is drawn again.
- The two dark blocks in `tokens.css` must be kept in step (a comment says so; the contrast
  test reads the first).
