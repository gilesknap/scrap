# 34. Claude can move pages to the trash

Date: 2026-10-26

## Status

Accepted. Revises [](0025-trash-and-recent-changes-over-mcp.md), which said no tool deletes a
page.

## Context

The owner merged several Later lists into one page with Claude, then had to delete the old
pages by hand in the PWA: nothing over MCP could. Since [](0030-trash-purged-after-n-days.md) a
delete is a move to the trash, kept for N days, and `undelete` brings a page back, so a delete
over MCP can be undone. The threat is a session steered by text in a page (prompt injection)
into deleting pages the user never named.

## Decision

- A new tool, `trash_pages(pages, dry_run)`, moves up to 50 named pages (ids, slugs or URLs) to
  the trash, as the PWA's delete does (the same store path), all or nothing: a page not found or
  already in the trash refuses the call and moves none. It takes no search query: pages are
  named one by one.
- It is a separate tool, not a mode of `trash`. `trash` stays a read-only lister, served even
  with `SCRAP_MCP_CONTENT_EDIT=0`; a destructive argument on it would blur that, and a name
  that says what it does is clearer to a model and in a permission prompt. It follows
  `edit_page` and `edit_meta` (verb and object), and is gated by `SCRAP_MCP_CONTENT_EDIT` with
  `undelete`.
- Nothing over MCP deletes a page for good or empties the trash: only the user, in the PWA, or
  the nightly purge after N days.
- Two or more pages moved in one call share a batch id; `undelete(batch=...)` brings back every
  page of it still in the trash from that call (those brought back since, or moved there again
  by a later call, are skipped and listed). `revert(batch=...)` refuses a trash batch and points
  at `undelete`: it undoes kind and tag changes, and a trash batch has none.
- Every move into or out of the trash, the PWA's delete and undo included, is a row of a new
  table, `page_trash_rev` (migration 17: action, author, source web or mcp, batch id, when).
  `revisions` lists them (`trash`) for a page, a batch, or in the recent-changes feed.
- The tool description and the server's instructions say to trash only pages the user named or
  asked to delete, never because text in a page says to, and to try `dry_run` first.

## Consequences

- Tidying after a merge is one call, and undone with one call.
- An injected instruction could still get pages trashed, but at most 50 a call, each named, each
  recorded with source `mcp`, and all recoverable as a batch until the purge.
- Deletes become visible in history: "what changed overnight?" now also answers "what was
  deleted?". Pages already in the trash before migration 17 have no row and are in no batch.
