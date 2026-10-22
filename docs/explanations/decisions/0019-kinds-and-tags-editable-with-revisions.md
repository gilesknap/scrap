# 19. Kinds and tags editable over MCP, made safe by metadata revisions

Date: 2026-10-22

## Status

Accepted. Revises [](0013-mcp-server-inside-the-app.md), which deferred changing an existing
page's kind.

## Context

`write` only adds pages or appends to Claude's own, so Claude could not fix the kind or tags of
the user's pages (e.g. imported notes that are really whiteboards). The add-only rule was the
safety: a session steered by injected text could not destroy anything. Kinds and tags are cheap
to get wrong, so letting Claude change them needs a way to see and undo every change.

## Decision

- MCP gains `edit_meta` (kind and tags of named pages, or of every page a search finds, with a
  `dry_run`), `rename_tag` (rename or merge, nested tags too), `revisions` and `revert`. Still no
  delete, and no tool changes the title or text of a page the user made.
- Every change to a page's kind or tags, by Claude or in the PWA (`PATCH /api/pages`), is a row
  of a new table, `page_meta_rev`: author, source (`mcp` or `web`), the kind and tags before and
  after, and the revision a revert undid. Full snapshots of kind and tag names: a few bytes, never
  a copy of the text or of a file, so no delta chains are needed. Text keeps its own full
  revisions in `page_rev`, unchanged (its `rev` is the PWA's edit token).
- Model-derived data (summaries, image descriptions, ingest's tags, the kind task boxes give a
  note) is not a revision: it can be made again.
- Coalescing: a change by the same author and source within `SCRAP_REVISION_WINDOW` seconds
  (default 300) of the page's latest revision being made folds into it, if nothing else changed
  the page's kind or tags between. A revert never folds, nor is folded into.
- `revert` restores the kind and tags from just before a revision, as a new revision.
- Kinds are the fixed set the schema allows (`note`, `todo`, `consume`, `whiteboard`,
  `document`, with the PWA's names `read`, `board`, `doc`), not free-form.
- A kind or tag edit does not change `updated_at`, as the PWA's never did.
- Migration 8 is additive, as 6 and 7: the table is made only if missing, so an older scrap still
  runs with `user_version` set back to 7. No backfill: a page's first change records its prior
  state.

## Consequences

- Claude can tidy kinds and tags in bulk; a mistaken or injected change is visible and revertible
  from `revisions`, and reverting is itself undoable.
- `page_meta_rev` grows with every edit burst; rows are independent snapshots, so old ones can be
  thinned later without rewriting others. Not built yet.
- Undoing a bulk change is one `revert` per page for now; a batch id could group them later.
- No PWA view of revisions yet: they are reached over MCP.
