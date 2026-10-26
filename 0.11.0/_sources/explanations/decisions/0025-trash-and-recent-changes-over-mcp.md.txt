# 25. The trash and a recent-changes feed over MCP

Date: 2026-10-24

## Status

Accepted. Revises [](0019-kinds-and-tags-editable-with-revisions.md) and
[](0022-page-text-editable-over-mcp-with-revisions.md), which both said there is no trash
over MCP.

## Context

An MCP session was asked "did the enrich job run last night?" and "restore the page I just
deleted". Neither could be answered. `revisions` needed a page or batch, so finding what changed
meant `recent` and then `revisions` once per page (about 45 calls). A page in the trash was "no
such page" to every tool, and the trash could be neither listed nor restored over MCP, though the
store already restores (`delete_page(undo=True)`) and the web API has `undelete`. The server's
instructions also said "nothing deletes a page" without saying deletes go to a trash, nor that
enrichment (ADR 20) is deliberately outside revision history.

## Decision

- `revisions` with no `page` and no `batch` is a recent-changes feed: the latest metadata and
  text revisions of every page not in the trash, newest first, bounded by `limit`.
- New `trash` lists the trashed pages (id, slug, title, kind, `deleted_at`), newest first. New
  `undelete(page, dry_run)` brings one back through the existing store call. It is reversible
  (the user can delete the page again) and loses nothing, so it has the trust model of
  `edit_meta`; it is gated by `SCRAP_MCP_CONTENT_EDIT` with the other tools that change
  content, and `trash` (read only) is not.
- `read` and `revisions` with a `page` accept a trashed page, read only, with `trashed` and
  `deleted_at`, so its last text and history can be checked before restoring it. Every other
  tool (`search`, `recent`, `todos`, `tags`, `drawing`, `edit_meta`, `edit_page`, `revert`,
  `revert_text`, `write` with `append_to`) still treats the trash as absent.
- Still no tool deletes a page or empties the trash.
- The instructions, reference and the `s` skill say that deletes go to a trash, which tools
  reach it, and that enrichment (`model_tag`, `enrichment`, `related`, `enrich_run`) is not in
  revision history, so `revisions` and `revert` neither show nor undo it.

## Consequences

- "What changed recently?" is one call, and a deleted page is recoverable from a session.
- Enrichment output is not revisioned and not revertible over MCP: it is derived data, a model
  tag can already be removed for good (the `off` state), and the enrich process picks better than
  a person choosing between its versions. A read-only enrich status (last run, queued, dead and
  paused counts) can follow separately.
- A session steered by injected text could restore a trashed page; the tool descriptions and
  instructions say to do it only when the user asked, and the harm is bounded (the page returns as
  it was and can be deleted again).
