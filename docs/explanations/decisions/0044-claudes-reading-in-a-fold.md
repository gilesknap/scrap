# 44. Claude's reading in a fold, and Claude's own images not read

Date: 2026-11-01

## Status

Accepted. Amends [ADR 43](0043-public-pages-a-static-site-scrap-pushes-to.md) (what a public
page holds) and [ADR 42](0042-mcp-clients-add-svg-and-files.md) (an SVG read as text).

## Context

Under every photo, SVG and file the app showed Claude's reading of it: its description, the
text read from it, a PDF's text. That is noise: on a maths paper every small triangle had a
block of Claude's text under it. Public pages left the readings out, so they also looked unlike
the private page. And an SVG Claude drew with `add_svg` was sent back to Claude to be read: one
model call per diagram, describing what Claude had just drawn and labelled (#521).

## Decision

- **One closed fold, "Claude's reading"**, under each photo, image or file that has one, in the
  app and on public pages. The same label for files, though scrap reads those itself. In the app
  it holds what the card showed before, with Regenerate (Generate, for one never read) at its
  end; where the reading is up to (waiting, failed, paused, a file being read, "couldn't read")
  stays outside it as words, with Retry or Resume beside them, so a failure is never folded
  away. It always starts closed and is not remembered.
- **Published closed**: the one `<details>` the publish mode writes without `open`. Its text is
  scrubbed as page text is and checked by the same rules, and Pagefind indexes it, so the site's
  search finds what is on a whiteboard. A PDF's fold has the text the app's shows (its first
  20,000 characters), which the PWA fetches when it publishes. Make public's warning lists
  "Claude's reading of its photos and files" when there is any.
- **Claude's own images are not read.** No ingest job is queued for an image of a capture
  Claude made over MCP (source `mcp`, author `claude`: `add_svg`, or Claude's `/mcp` upload),
  even when asked (Reprocess, Retry). The decision keys on the capture, not the file: the same
  file in one of the owner's captures is read as before. Files (a PDF, a text file) Claude
  uploads are still read for search: that is scrap's own reading, no model.
- **They show nothing under them**, in the app and on public pages: no fold, no note, no
  Generate, even one read before 1.3.3. Their alt, Claude's label, is the image's alt in the app
  and on the public page, and is what search finds: it is in the page's text (`![label](...)`),
  which is indexed with the page. No separate description is stored for it, as one would count as
  a reading elsewhere (a board's write-up, the image write-up on request).
- Old readings of Claude's images are left in place, and only hidden; the owner may drop them
  with a one-off procedure (issue #521), not code.

## Consequences

- A page reads as the owner's text and images, with Claude's write-up and summary; what search is
  indexed by is a tap away, and a public page looks like the private one.
- No model call for a diagram Claude draws. Its SVG's own words (`<title>`, `<text>`) are no
  longer indexed on their own, only its label: `add_svg`'s description asks for a label that says
  what it shows.
- A page of Claude's diagrams is no longer made a board by their readings, so it gets no
  write-up of its own; Ask Claude still reads the page's text.
- An imported page (source `import`) is read as any import is, Claude's diagrams included.
