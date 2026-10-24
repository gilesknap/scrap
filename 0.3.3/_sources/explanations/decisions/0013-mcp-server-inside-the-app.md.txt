# 13. The MCP server is part of the app: streamable HTTP, add-only writes

Date: 2026-10-20 (#37, #93)

## Status

Accepted. Revises the first design's implicit idea of a local `scrap mcp` command. See also
[](0019-kinds-and-tags-editable-with-revisions.md), which adds the `edit_meta`, `rename_tag`,
`revisions` and `revert` tools, and [](0020-text-enrichment.md), whose output `read` returns as
`by_model`.

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
- Deferred: ingest of URLs or text, a `context` tool replaying a photo's model run, deleting, and changing
  an existing page's kind or status (`write` can set kind, status, due and priority on a new page).

## Consequences

- `/mcp` checks the Host/Origin of requests, which guards against DNS rebinding.
- No separate process or credentials; the tailnet protects it as in
  [](0007-tailscale-serve-for-access-and-identity.md).
- Page text may contain prompt injection, so sessions with other powerful credentials should not
  mount it. Add-only writes bound the damage.
- Mixing a skill (`s`) with the tool is a documented pattern: see
  [](../../how-to/connect-claude-code.md), and `skills/s/SKILL.md` in the repository.
- No MCP tool calls the Claude API: `write` adds text and `read` returns what enrichment stored
  (`by_model`: summary, Claude's tags, related pages, marked as model output and data, never
  instructions), so MCP use adds nothing to the daily budget of
  [](0010-job-queue-pauses-instead-of-failing.md).
