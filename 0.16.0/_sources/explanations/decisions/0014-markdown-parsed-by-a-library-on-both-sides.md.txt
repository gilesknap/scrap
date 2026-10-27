# 14. Page text is Markdown, parsed by a library on both sides

Date: 2026-10-20 (#71, #102)

## Status

Accepted

## Context

Early rendering and importing used hand-written regexes. They mis-handled tables, code, nested
brackets and pathological inputs, and the client and server disagreed about what a link or image was.
Search needed plain text from the same parse.

## Decision

- Both sides use the same grammar: CommonMark plus tables, strikethrough, footnotes, `[[slug|label]]`
  page links, raw HTML as text, and a line break kept as one.
- The PWA renders with markdown-it in a lazy chunk (`render.ts`); a post-parse pass allows only
  http(s), mailto, page and in-page links (`rel=noopener`) and only this server's images.
  ` ```mermaid ` blocks are drawn by a bundled, separately loaded Mermaid with
  `securityLevel: 'strict'`, so the CSP does not change.
- The server uses markdown-it-py (`scrap/markdown.py`) to produce search text (link/image text, not
  addresses; code as typed) and for the importer, which rewrites links, images and wiki links found by
  the parse and mapped back to source positions, so code is never touched.
- Parsers must be linear in the text. Migration 0004 re-indexed every page this way.
- Search deliberately does not index addresses.

## Consequences

- Rendering offline works once the chunk is cached; before that, text shows as typed.
- Two parser implementations must be kept in step, covered by tests and docs.
- A hand-written URL is found by its link text, not its domain, by choice.
