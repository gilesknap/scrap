# MCP server

scrap serves an [MCP](https://modelcontextprotocol.io) server at `/mcp` in the same process as
the PWA and its API: Streamable HTTP, stateless (every request stands alone, so a restart drops
no session), JSON replies. A Claude Code session connects with one line and needs nothing
installed; see [](../how-to/connect-claude-code.md). Tools show in a session as
`mcp__scrap__search`, `mcp__scrap__read` and so on.

Every tool result is JSON (MCP structured content, also sent as its text). Page text (titles,
bodies, summaries, snippets, tags, what Claude read from photos) is in fields of that JSON, as
data: the server's instructions tell the model it is the user's text, never instructions to it.

## Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search` | `query`, `limit` (1-50, default 20), `offset` (0-200) | `{results, offset}`: each `{id, slug, url, kind, status, updated_at, tags, title, snippet}`, best first. `query` takes the search box's syntax (see `GET /api/search` in [](api.md)): words (AND, as prefixes), `-word`, `"phrase"`, `kind:`, `tag:`, `is:open`/`is:done`/..., `is:personal`, `is:work`, `is:claude`, `after:`, `before:`, `date:created`. The snippet is plain text |
| `read` | `page` (id or slug) | `{page, content, images, links, backlinks}`. `page`: id, slug, url, kind, status, tags, dates, `rev`, `written_by_claude`, `origin`, other fields. `content`: `title`, `summary`, `body_markdown`. `images`: each file's `url`, mime, filename, and what Claude made of it (`description`, `text`, `image_kind`, `has_drawing`), never the image itself. `links`: the `[[slug]]` links in the body; `backlinks`: pages linking here |
| `recent` | `limit` (1-50), `kind` (`note`, `todo`, `read`, `board`, `doc`) | `{results}`: pages newest change first, rows as `search` without a snippet |
| `todos` | `limit` (1-100) | `{results}`: todos neither done nor cancelled, newest first |
| `tags` | `prefix`, `limit` (1-2000, default 300) | `{tags: [[tag, n]], total}`, most used first; `a` counts the pages of `a/b` too |
| `write` | `title`, `body` (Markdown), `origin`, `tags`, `kind` (default `note`), `status`, `append_to`, `key` | `{id, slug, url, created}` |

## Writing

- `write` makes a new page, or with `append_to` (an id or slug) adds `body` at the end of a page
  written over MCP, as a new revision, and adds its `tags`. It never changes or deletes any other
  page: appending to a page the user made is refused. There is no delete tool.
- **Provenance.** The page's capture has source `mcp` and author `claude` (as has its
  revision), and `fields.origin` holds `origin` (free text, at most 200 characters: the repo or
  directory and the date, say). The PWA shows such a page with a *Written by Claude* badge (its
  origin as the tooltip), and `is:claude` finds them. Clients of `POST /api/captures` cannot send
  source `mcp`.
- **Idempotency.** With `key` (at most 128 characters), a retry with the same key adds nothing
  and returns the same page with `created: false`. Without it, every call adds.
- **Limits.** `title` 1 to 200 characters (whitespace collapsed); `body` at most 200 kB of UTF-8
  per call, and a page appended to at most 1 MB; at most 20 tags, each 1 to 64 characters once
  normalised as imported tags are (one space between words, no leading `#`, lower case;
  `a/b` nests); `kind` one of `note`, `todo`, `read`, `board`, `doc`; `status` (`open`,
  `in_progress`, `done`, `cancelled`) only for a todo or a read. Text must be valid Unicode with
  no NUL (a lone surrogate is refused). A request over 2 MB is `413`. A refused call is an MCP
  tool error with the reason; nothing is saved.

## Security

The service has no login: it is reachable only over the tailnet, through Tailscale Serve, like
the rest of scrap. `/mcp` also checks the `Host` header against loopback and the hosts of
`SCRAP_PUBLIC_URL` (`421` otherwise), and an `Origin` header, if sent, against those origins
(`403`), so a web page cannot reach it by DNS rebinding. Pages may hold injected text, so a
session holding powerful credentials should treat what it reads as data (see the design's
security posture).

Not yet: a `context` tool returning the stored ingest run of a photo (its messages, for
discussing it with the model that made it), and an `ingest` tool.
