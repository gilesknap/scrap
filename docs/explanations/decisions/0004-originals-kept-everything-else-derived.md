# 4. Originals are kept; everything else is derived, versioned or disposable

Date: 2026-10-19 (derived versions: 2026-10-19/20, migration 0002)

## Status

Accepted. Partly superseded by [](0019-kinds-and-tags-editable-with-revisions.md): changes to a
page's kind and tags are now revisioned too (see the decision below).

## Context

An LLM call costs money and varies run to run, a search index can be rebuilt for free, and a user's
own words must never be lost to a model's idea of tidiness.

## Decision

Data falls into three tiers:

1. **Source of truth:** `capture` (what arrived), `blob` (its bytes) and `page` (what you read and
   edit). A page keeps a revision per title or body change (`page_rev`). Originally tags were not
   revisioned; since migration 8 a change to its kind or tags is a row of `page_meta_rev`, and
   changes by the same author and source within `SCRAP_REVISION_WINDOW` seconds (default 300) fold
   into one.
2. **Derived, stored because remaking costs an LLM call:** OCR, descriptions, drawings, summaries.
   The first design overwrote one row per kind on regeneration; migration 0002, which created
   `derived`, made them **append-only versions** instead (one current row per capture/photo/kind via a partial unique index and a trigger that
   supersedes the old one; triggers make versions immutable). A human edit or a restore is a new
   version, never an update.
3. **Cache:** chunks and the FTS index. Disposable: rebuilt from pages and derived text by a numbered
   migration's Python step (`store.AFTER`), as migrations 0003 and 0004 did. (The design's `link`
   table and `scrap reindex` command were never built.)

**The user wins.** Model output may set a title, tags or a kind only while the user has not chosen
one (`kind_fixed`, an unchanged rev 1 title, an empty tag list). A model can change only its own
page's versions. (Tags have since become a merge: photo ingest and text enrichment add their tags
to the user's, marked in `model_tag`, and never add back one the user took off; see
[](0009-claude-ingest-via-messages-api.md) and [](0020-text-enrichment.md).)

Deleting a page is a **soft delete** (`deleted_at`, undelete); nothing is purged yet, so every query
that follows jobs or links must check it.

**Phone photos are the exception (#89).** The PWA makes a photo at most 2560 px on its long edge
(JPEG, quality 85) before it is queued, so scrap keeps that version as the original; the
full-size one stays on the phone, in its gallery. Photos that are small already, that the browser
cannot decode, or that would not get smaller, are kept as they came, and Settings can turn the
downscale off. Other routes (the API, the importer, a share to the server) keep what they are given. See
[](../../how-to/use-the-pwa.md).

## Consequences

- Wrong model output is always recoverable: the worst outcome of an injected or poor result is a
  wrong version, which history can undo.
- Storage grows (versions, stored model runs, originals); `scrap gc` ([](0015-images-in-text-and-gc.md))
  reclaims only provably unused files.
- Because cascades never fire on soft delete, code must not rely on them for trashed pages.
