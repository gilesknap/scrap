# 13. The MCP server is part of the app: streamable HTTP, add-only writes

Date: 2026-10-20 (#37, #93)

## Status

Accepted. Revises the first design's implicit idea of a local `scrap mcp` command.

## Context

Claude is meant to be how scrap is queried: search, read and add pages. A client session needs a
server it can add with one line, from anywhere on the tailnet.

## Decision

- Served at `/mcp` by the official MCP SDK inside the FastAPI process: Streamable HTTP, stateless,
  JSON replies. A stdio command was rejected because it needs a shell where the database is, which
  no client session has.
- Tools: `search` (the search box's syntax), `read`, `recent`, `todos`, `tags`, and `write`.
  Results carry each page's PWA URL (`$SCRAP_PUBLIC_URL/p/<slug>`) and its images as URLs, so Claude
  links to the PWA instead of trying to show pictures. Page text is returned as JSON field data.
- **`write` only adds**: a new page, or a section appended to a page written over MCP. It cannot edit
  or delete the user's own pages. Provenance is the capture source `mcp` (which HTTP clients cannot
  send), author `claude`, and `fields.origin`; the PWA shows a badge and `is:claude` filters. A
  client key is hashed into the capture id, reusing the retry key mechanism.
- Deferred: ingest of URLs or text, a `context` tool replaying a photo's model run, deleting, setting
  a kind, ticking a todo.

## Consequences

- No separate process or credentials; the tailnet protects it as in
  [](0007-tailscale-serve-for-access-and-identity.md).
- Page text may contain prompt injection, so sessions with other powerful credentials should not
  mount it. Add-only writes bound the damage.
- Mixing a skill (`scrap-post`) with the tool is a documented pattern.
