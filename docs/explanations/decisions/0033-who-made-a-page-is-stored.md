# 33. Who made a page, and where a text revision came from, are stored

Date: 2026-10-26

## Status

Accepted

## Context

scrap never stored who made a page. Each feature worked it out from the page's captures and the
topic table (#280): Written by Claude from the first capture's source, `is:claude` from any
capture's, a `scrap gc` review page from a `gc` capture. Step 2 of #280 gathered those tests into
`store/roles.py`; they gave the same answer for every page, but by different routes, and each read
the capture table.

A text revision's author was also its source (#153). MCP writes as `claude`, and an author of
`claude` was what made a revision Claude's: `is:claude-edited`, and whether an MCP edit may fold
into the revision before it. A web edit's author is the identity header's value, so a request
naming `claude` in that header made a web edit look like Claude's.

## Decision

- `page.made_by` is `human`, `claude`, `topic` or `gc` (a `CHECK`). It is set once, when the page
  is made, from how it is made: an MCP `write` is `claude`, `scrap gc`'s review page `gc`, a topic
  page `topic`; a PWA or share capture, an import and the Pinned page `human`. A trigger refuses
  any later change, so editing, re-kinding, adding photos, appending and the trash never touch it.
- `is:claude`, MCP `read`'s `written_by_claude`, the PWA's Written by Claude badge, `Store.append`'s
  check and `REVIEW` (gc's review page, wherever health checks, retention and `scrap gc --report`
  use it) read the column.
- The topic test stays the `topic` table, not `made_by`: the table holds the key that keeps Claude
  from making a topic again, and the topic's sources. Both are written in one transaction and
  never change, so they agree.
- `page_rev.source` is `web` or `mcp`, as `page_meta_rev.source` is. `mcp` is Claude's text: MCP's
  edits, reverts and appends, and the task boxes Claude adds for photo ingest and enrich. Every
  other revision is `web`, including scrap's own (an import, `scrap gc`, a new topic page).
  `is:claude-edited`, folding a burst (same author *and* source) and putting back the kind of a
  todo whose boxes Claude took off read it, not the author.
- The identity header's value `claude` (in any case, spaces aside) counts as no header: the author
  is `tagged`. No request header can name MCP's author.
- Migration 16 adds both columns. `made_by` is backfilled with what `roles` said before
  (`INFERRED_MADE_BY`: a topic, else a `gc` capture, else a first capture from MCP, else
  `human`); `source` is `mcp` where the author is `claude`, as #153 asked. On the live data the
  backfill gives `claude` to exactly the pages the old `is:claude` found.

## Consequences

- Who made a page is one column read, and no longer depends on the captures a page has later.
- The task boxes Claude adds for ingest and enrich are `mcp` too, so the backfill and new
  revisions agree; telling them apart from MCP's own edits would need a third source.
- Behind an authenticating proxy the identity header must still be set (`identityHeader`,
  `SCRAP_IDENTITY_HEADER`), or every web change is `tagged`.
- An older scrap cannot run on a migrated database even with `user_version` set back: it writes
  text revisions without naming their columns, which the extra `page_rev` column refuses. Going
  back past migration 16 needs the pre-upgrade backup, as the upgrade guide says.
- `made_by` is part of the baseline at the 1.0 squash (#267).
