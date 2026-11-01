# 41. MCP clients download files under /mcp

Date: 2026-10-31 (#479)

## Status

Accepted

## Context

`read`, `search` and `current_page` give image and file URLs under `/api/blobs/{sha}`. Behind
Cloudflare Access only `/mcp` takes the service token, so an MCP client sent there gets the
email login page, not the file. A client could not save an attachment, publish a page with its
pictures, or get a drawing past the `drawing` tool's 200 kB cut.

The PWA fetches `/api/blobs/...` from the browser with no bearer token, so `/api` cannot need
one. Telling a machine request from a browser one (by the Access JWT's claims, or the
`CF-Access-Client-Id` header) would tie scrap to one proxy and add moving parts.

## Decision

- The read-only GETs a client needs are served under `/mcp` too, by the `/api` routes' own
  handlers (`mcp_files.py` registers each one on a second path; a missing one stops startup):
  `/mcp/blobs/{sha}`, `/preview` and `/uses`; `/mcp/pages/{key}/download`;
  `/mcp/captures/{cid}/photos/{sha}/drawing` and `/versions`. One more is `/mcp` only:
  `.../drawing.excalidraw`, the whole current drawing as an `.excalidraw` file (as a page's
  download has it).
- `BearerAuth` already guards `/mcp` and everything under it, and the Access application on path
  `/mcp` covers its subpaths, so they need the same headers as `/mcp`: no new auth code and no
  Cloudflare change. With no token set they are open, as `/mcp` is.
- They are GETs, so `hostguard` checks their `Host` (as for every route) and no `Origin` is
  needed: curl works.
- Results keep `url` (the browser's link) and add `download_url` (images, files, `page`),
  `drawing_download_url`, `image_download_url` (search rows) and the `drawing` tool's
  `download_url`.

## Consequences

- The `/api` paths and the PWA are unchanged; nothing is written through `/mcp/...`.
- A client with the MCP headers can read every stored file by hash, as anyone past the email
  login can.
- A new download for MCP clients is a line in `mcp_files.MIRRORED`.
