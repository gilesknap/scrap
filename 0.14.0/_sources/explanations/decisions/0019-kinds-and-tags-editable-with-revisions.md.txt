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
  `dry_run` and a page limit), `rename_tag` (nested tags too; the same limit; merging into a tag
  in use only with `merge`; never into its own child), `revisions` and `revert`. Still no delete,
  and no tool changes the title or text of a page the user made. History is reached over MCP
  only: no PWA view or HTTP revert endpoint.
- Every change to a page's kind or tags, by Claude or in the PWA (`PATCH /api/pages`), is a row
  of a new table, `page_meta_rev`: author, source (`mcp` or `web`), the kind, whether it was fixed
  (`kind_fixed`) and tags before and after, the default fields a new kind added, the revision a
  revert undid, and a batch id. Full snapshots of kind and tag names: a few bytes, never
  a copy of the text or of a file, so no delta chains are needed. Text keeps its own full
  revisions in `page_rev`, unchanged (its `rev` is the PWA's edit token).
- Model-derived data (summaries, image descriptions, ingest's tags, the kind task boxes give a
  note) is not a revision: it can be made again.
- Coalescing: a change by the same author and source within `SCRAP_REVISION_WINDOW` seconds
  (default 300) of the page's latest revision being made folds into it, if nothing else changed
  the page's kind or tags between; a fold that ends where the revision started drops it. A
  revert, and any change in a batch, never folds, nor is folded into: a batch's revisions stay
  exactly what that one call did, so the batch can be undone as a whole.
- `revert` restores the whole snapshot from just before a revision (kind, fixed or not, tags)
  and takes off the defaults its kind change added unless changed since, as a new revision: a
  page Claude filed and then reverted follows its task boxes and ingest again. Being a whole
  snapshot, it also drops unrecorded (derived) tags and kinds added since; `dry_run` shows this.
- Batches: an `edit_meta` of a query or of several pages, and every `rename_tag`, stamps its
  revisions with one batch id; `revert(batch=...)` undoes them in one transaction as a new batch,
  itself undoable at once. If any page of the batch changed kind or tags since, the batch revert
  is refused, saving nothing (never a silent clobber); its pages can still be reverted one by
  one. Pages in the trash are skipped.
- Revision ids are `AUTOINCREMENT`: a dropped burst's id is never handed to another page's
  revision, since tools give ids out and `revert` takes them back.
- Kinds are the fixed set the schema allows (`note`, `todo`, `consume`, `whiteboard`,
  `document`, with the PWA's names `read`, `board`, `doc`), not free-form.
- A kind or tag edit does not change `updated_at`, as the PWA's never did. A kind given to
  `edit_meta` is fixed even if it is the page's kind already, as the PWA's PATCH does.
- Migration 8 is additive, as 6 and 7: the table is made only if missing, so an older scrap still
  runs with `user_version` set back to 7. No backfill: a page's first change records its prior
  state.

## Consequences

- Claude can tidy kinds and tags in bulk; a mistaken or injected change is visible and revertible
  from `revisions`, and reverting is itself undoable.
- `page_meta_rev` grows with every edit burst; rows are independent snapshots, so old ones can be
  thinned later without rewriting others. Not built yet.
- No PWA view of revisions yet: they are reached over MCP.

## Deploying over a database already at version 8

A local build of other work (text enrichment) also numbered its migration 8, and a canary
database already at `user_version` 8 from it would skip this one: then `page_meta_rev` is
missing and every tag or kind edit, PWA's too, fails. Both migrations are additive and
idempotent (`IF NOT EXISTS`), so before the first deploy of any build containing both, set
`PRAGMA user_version = 7` on that database, and renumber whichever lands second to 9.

As merged, this change is migration 8 (`add_meta_revs`) and text enrichment
([](0020-text-enrichment.md)) is migration 9 (`add_enrich`). A database at version 8 made by the
merged code is simply migrated to 9 on its first start. The workaround above applies only to a
database numbered 8 by the earlier local build: with `user_version` set back to 7, the next start
runs migrations 8 and 9 in order, and each leaves tables that already exist alone.

A database that already has a `page_meta_rev` table from an earlier revision of this change
(only throwaway test databases: the canary has none) must have it dropped first (`DROP TABLE
page_meta_rev`): migration 8 then fails loudly on the missing columns, or, at version 8, is
skipped and inserts fail.
