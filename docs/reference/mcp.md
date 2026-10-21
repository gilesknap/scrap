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
| `search` | `query`, `limit` (1-50, default 20), `offset` (0-200) | `{results, offset}`: each `{id, slug, url, kind, status, due, priority, updated_at, tags, title, snippet}` (`due` and `priority`: a todo's, else `null`) plus its images (see Images below), best first. `query` takes the search box's syntax (see `GET /api/search` in [](api.md)): words (AND, as prefixes; they also match what Claude read from the page's photos), `-word`, `"phrase"`, `kind:`, `tag:`, `is:open`/`is:done`/..., `is:personal`, `is:work`, `is:claude`, `has:image`, `has:drawing`, `image:K`, `after:`, `before:`, `date:created`, a todo's `due:` (`due:today`, `due:<today` overdue, `due:>today`, `due:<=2026-11-01`, `due:none`) and `priority:` (`high`, `medium`, `low`, `none`), and `sort:updated`, `sort:created` (newest first), `sort:title` (A to Z), `sort:due` (soonest first) or `sort:priority` (high first; pages with none last either way), with `-sort:` reversing one (`-sort:created`: oldest first). The snippet is plain text |
| `read` | `page` (id or slug) | `{page, content, images, links, backlinks}`. `page`: id, slug, url, kind, status, `due`, `priority`, tags, dates, `rev`, `written_by_claude`, `origin`, other fields. `content`: `title`, `summary`, `body_markdown`. `images`: each file's `url`, `thumbnail_url` (images only, else `null`), mime, filename, and what Claude made of it (`description`, `text`, `image_kind`, `has_drawing`), never the image itself. `links`: the `[[slug]]` links in the body; `backlinks`: pages linking here |
| `recent` | `limit` (1-50), `kind` (`note`, `todo`, `read`, `board`, `doc`) | `{results}`: pages newest change first, rows as `search` (images included) without a snippet |
| `todos` | `limit` (1-100), `sort` (`due` or `priority`) | `{results}`: todos neither done nor cancelled, rows as `search` (with `due` and `priority`), newest first, or soonest due or highest priority first (those with none last) |
| `tags` | `prefix`, `limit` (1-2000, default 300) | `{tags: [[tag, n]], total}`, most used first; `a` counts the pages of `a/b` too |
| `write` | `title`, `body` (Markdown), `origin`, `tags`, `kind` (default `note`), `status`, `due`, `priority`, `append_to`, `key` | `{id, slug, url, created}` |

## Images

A photo page is a plain `note` whose body is only an image embed, so its title, tags and
snippet may say little. Every row of `search`, `recent` and `todos` therefore says what images
the page has (fields added in place; older clients can ignore them):

- `image_count`: how many image files the page's captures hold (`0`: none).
- When it is above 0, the first image's `image_kind` (what Claude took it for: `photo`,
  `whiteboard`, `handwriting`, `diagram`, `screenshot`, `document` or `other`),
  `image_description` (Claude's 1-3 sentences about it), `image_url` (the original file) and
  `thumbnail_url` (a JPEG at most 480 pixels a side, HEIC converted). `image_kind` and
  `image_description` are `null` until the photo has been read (ingest queued, failed or off).

Search filters (the PWA's search box takes them too): `has:image` (a page with an image),
`has:drawing` (one with a current drawing), `image:K` (an image Claude took for kind `K`, e.g.
`image:photo`, `image:whiteboard`); `-` before any of them excludes. A filter alone lists newest
first, so **`search` with `has:image` is "my recent photos"**. A word in a photo's description or
its transcribed text finds the page (Claude's results are indexed as the page's text), so
`mantis` finds a photo of one.

**Can a client fetch the image?** The URLs are plain HTTPS `GET`s with no login, like the rest
of scrap: anything on the tailnet can fetch them (`curl -o p.jpg <thumbnail_url>`, then look at
the file; Claude Code's Read shows an image). A client off the tailnet cannot, and a built-in
web-fetch tool that runs elsewhere, or refuses private hosts, will not reach it.

**Can `read` return the image itself?** Not yet: results are JSON (URLs and Claude's text). MCP
can carry images as `image` content blocks; a later option could return a page's thumbnails
that way (480 px JPEGs, so a few hundred kB each).

## Writing

- `write` makes a new page, or with `append_to` (an id or slug) adds `body` at the end of a page
  written over MCP, as a new revision, and adds its `tags`. It never changes or deletes any other
  page: appending to a page the user made is refused. There is no delete tool.
- **Due dates and priorities.** A todo may have `due` (`YYYY-MM-DD`) and `priority` (`high`,
  `medium`, `low`); on another kind they are refused, as `status` is on a note. With
  `append_to`, they change those of the todo appended to (Claude's own; `none` clears one), and
  `body` may then be empty: that adds no revision and leaves `updated_at` as it was.
- **Provenance.** The page's capture has source `mcp` and author `claude` (as has its
  revision), and `fields.origin` holds `origin` (free text, at most 200 characters: the repo or
  directory and the date, say). The PWA shows such a page with a *Written by Claude* badge (its
  origin as the tooltip), and `is:claude` finds them. Clients of `POST /api/captures` cannot send
  source `mcp`.
- **Idempotency.** With `key` (at most 128 characters), a retry with the same key adds nothing
  and returns the same page with `created: false`. Without it, every call adds. Keys are
  global, not per session: use a random value per post, reused only to retry it. A key is
  matched together with its target (a new page, or the page appended to, by id or slug), so
  reusing one for another page writes there rather than being taken for a retry.
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
