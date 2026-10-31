# 42. MCP clients add SVG diagrams and files to pages

Date: 2026-10-31 (#480)

## Status

Accepted

## Context

An MCP client could read, edit and (with [ADR 0041](0041-mcp-clients-download-under-mcp.md))
download, but not add an image or a file to a page. A diagram for a maths question was ASCII
art; a chart or a screenshot Claude made elsewhere could not live in scrap.

Two kinds of file need two routes. SVG is text: Claude can write an exact, labelled diagram for
about the cost of a paragraph, so a tool argument suits it. A PNG, a PDF or a scan already on
disk is binary, and base64 through a tool call is slow, costly and error-prone.

Writing is a step up from downloading, and SVG is markup that a browser can run if it is
opened directly.

## Decision

- **`add_svg`, an MCP tool.** It takes the page, the markup, alt text, an optional file name, an
  optional `after` (text that must occur exactly once, as `edit_page`'s `old`), a `key` and
  `dry_run`. The embed goes right after the line `after` ends on: a paragraph is split there;
  in a tight list (the owner's decision) the line ends with a hard break (`\`) and the embed
  follows on the next line at the item's indent, so the list stays tight; in a loose list or
  a quote it is a paragraph of its own in the item or quote. A block that cannot be split (a fenced or
  indented code block, a table, `$$` or `\begin{...}` maths, a heading) has it after its end.
  The text is parsed as the page is rendered to find the block (`store/placing.py`, tabs to
  stops of four), and each place tried is parsed again: kept only if the page's blocks, the
  item or quote the embed is in, the lists' tightness and the rendered text are unchanged
  (a split that would start a list, or cut a link or bold text in two, falls back to the end
  of the paragraph); if no place passes, the embed goes at the end of the text. So a diagram sits under its question. Without
  `after` it goes at the end. The same `key` with another SVG is refused, `dry_run` too. It stores the SVG as a new capture of the page and embeds it as
  the PWA's Add photo does (`store.add_photos`), with the alt text.
- **The upload, over HTTP.** `POST /api/pages/{key}/captures` is also served at
  `POST /mcp/pages/{key}/captures`, by the same handler, so `BearerAuth` and the Cloudflare
  Access application on `/mcp` gate it with the headers a client already sends. It keeps the
  ULID retry key, `415` and `413`, and gains `alt`, `after` and an `added` list of download URLs.
  `mcp_files` lists it apart from the GET mirrors (`WRITES`), and a missing route still stops
  startup.
- **Both are Claude's.** A request by an `/mcp/...` path is attributed to `claude` with source
  `mcp` (`uploads.by_mcp`), and the embed is a text revision with source `mcp`, as `add_svg`'s
  is: `is:claude-edited` finds it, `revisions` lists it, `revert(page, to_rev)` takes the embed
  out. Both wake the ingest worker, as a PWA upload does.
- **One setting.** `SCRAP_MCP_UPLOAD`, on by default, parsed as `SCRAP_MCP_CONTENT_EDIT` is
  (`0`, `false`, `no` or `off` turns it off; any other value stops startup). Off, `add_svg` is
  not listed and the route is not served. It is the only gate: `SCRAP_MCP_CONTENT_EDIT=0` does
  not limit either (adding an image is not editing the user's text; the owner's decision).
- **SVG is sanitised on every upload** (`svg.py`; `add_svg`, the `/mcp` upload, the PWA, a
  Markdown import, which reports one it refuses and imports the rest). It must
  be UTF-8, at most 1 MiB, with an `<svg>` root. It is parsed by the standard library with no
  DOCTYPE (one naming only an external DTD, as matplotlib writes, is dropped unread; one with an
  internal subset is refused), so no entity can be declared, expanded or fetched (no new
  dependency). Only an
  allow-list of drawing elements is kept, with no `on*` attribute, no `href` but to a
  `#fragment` (or a raster `data:` URL on an image), no `ping`, and in CSS (`<style>`, `style`
  and the presentation attributes that take a url) no comment, no @-rule but `@font-face`,
  `@media` and `@keyframes` (another becomes `@x-...`, which a browser ignores), no `url()` but
  to a fragment or a `data:` font (each one checked on its own), and no `image-set()`, `src()`,
  escape or quoted URL; the passes repeat until nothing changes, so no removal can join what
  is left into a rule.
- **And a CSP that loads nothing.** Every stored file but a PDF, and an SVG's preview too, under
  `/api` and `/mcp`, has `Content-Security-Policy: sandbox; default-src 'none'; style-src 'unsafe-inline';
  img-src data:; font-src data:` and `nosniff` (`STRICT_HEADERS`): opened as a page it runs no
  script and fetches nothing, even if the sanitiser misses something, the file predates it,
  or the file is other markup (an imported `.xml` with an `<svg>` root). An image or a text
  file shows as before; a PDF keeps `sandbox` alone, as a browser's PDF viewer needs more. In `<img>`, where the
  PWA shows it, an SVG runs nothing and loads nothing anyway.
- **An SVG is never rasterised.** `/api/blobs/{sha}/preview` serves the SVG itself at either size,
  with the same headers; nothing decodes it with Pillow (preview, Claude's JPEG, a page's
  download with previews).
- **Read as text.** Ingest puts its words (`<title>`, `<desc>`, `<text>`) as the image's text at
  once, with no model call, as a PDF's text layer is read; then Claude reads its markup (the first
  20,000 characters) as a text block instead of an image, for the description, title and tags,
  with no drawing asked for. A write-up (a board's, or one asked for) sends an SVG image the
  same way: its markup as text blocks, where a photo's JPEG would go. The markup is untrusted
  data, quoted, as page text is.

## Consequences

- A diagram can go exactly where it belongs, and its labels are searchable without a model.
- An SVG uploaded from the PWA now shows, has a preview and is read, where before its preview
  failed and its ingest was charged as an undecodable image. It is stored sanitised, so the file
  kept is not byte for byte the one sent; a malformed SVG, one with an internal DTD subset or entities, or one over 1 MiB
  is refused.
- A gist renders SVG from its raw URLs (`gist.githubusercontent.com/.../raw/file.svg`) and
  `gh gist create` takes it as a text file, so a page with SVG diagrams can be published as a gist
  of text files alone, with no clone or push for binaries.
  Update (2026-10-31): removed by [](0043-public-pages-a-static-site-scrap-pushes-to.md), with
  the scrap-to-gist skill; public pages are planned to go to a static site instead.
- A client with the MCP headers can add files to any page, unless `SCRAP_MCP_UPLOAD=0`.
- An SVG stored before #480 was not sanitised; `STRICT_HEADERS` still keeps it from running or
  fetching anything when it is opened.
