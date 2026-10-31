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
  optional `after` (text that must occur exactly once, as `edit_page`'s `old`: the embed goes on
  its own lines after the line it ends on, so a diagram sits under its question; else at the
  end), a `key` and `dry_run`. It stores the SVG as a new capture of the page and embeds it as
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
  out. With `SCRAP_MCP_CONTENT_EDIT=0` both take only pages written over MCP.
- **One setting.** `SCRAP_MCP_UPLOAD`, on by default, parsed as `SCRAP_MCP_CONTENT_EDIT` is
  (`0`, `false`, `no` or `off` turns it off; any other value stops startup). Off, `add_svg` is
  not listed and the route is not served.
- **SVG is sanitised on every upload** (`svg.py`; `add_svg`, the `/mcp` upload, the PWA). It must
  be UTF-8, at most 1 MiB, with an `<svg>` root. It is parsed by the standard library with no
  DOCTYPE allowed, so no entity can be declared, expanded or fetched (no new dependency). Only an
  allow-list of drawing elements is kept, with no `on*` attribute, no `href` but to a
  `#fragment` (or a raster `data:` URL on an image), and no `url()` out of the file or
  `@import`. This is defence in depth: every stored file is already served with
  `Content-Security-Policy: sandbox` and `nosniff`, and the PWA shows images in `<img>`, where
  no script runs.
- **An SVG is never rasterised.** `/api/blobs/{sha}/preview` serves the SVG itself for any size,
  with the same headers; nothing decodes it with Pillow (preview, Claude's JPEG, a page's
  download with previews).
- **Read as text.** Ingest puts its words (`<title>`, `<desc>`, `<text>`) as the image's text at
  once, with no model call, as a PDF's text layer is read; then Claude reads its markup (the first
  20,000 characters) as a text block instead of an image, for the description, title and tags,
  with no drawing asked for. The markup is untrusted data, quoted, as page text is.

## Consequences

- A diagram can go exactly where it belongs, and its labels are searchable without a model.
- An SVG uploaded from the PWA now shows, has a preview and is read, where before its preview
  failed and its ingest was charged as an undecodable image. It is stored sanitised, so the file
  kept is not byte for byte the one sent; a malformed SVG, one with a DOCTYPE or one over 1 MiB
  is refused.
- A gist renders SVG from its raw URLs (`gist.githubusercontent.com/.../raw/file.svg`) and
  `gh gist create` takes it as a text file, so a page with SVG diagrams can be published as a gist
  of text files alone, with no clone or push for binaries.
- A client with the MCP headers can add files to any page (to Claude's own only, with content
  editing off), as it could already edit any page's text.
- The board write-up still sends only raster images: an SVG board's write-up has its text,
  description and the page, not its markup.
