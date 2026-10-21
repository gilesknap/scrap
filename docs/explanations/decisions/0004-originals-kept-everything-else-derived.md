# 4. Originals are kept; everything else is derived, versioned or disposable

Date: 2026-10-19 (derived versions: 2026-10-19/20, migration 0002)

## Status

Accepted

## Context

An LLM call costs money and varies run to run, a search index can be rebuilt for free, and a user's
own words must never be lost to a model's idea of tidiness.

## Decision

Data falls into three tiers:

1. **Source of truth:** `capture` (what arrived), `blob` (its bytes) and `page` (what you read and
   edit). A page keeps a revision per title or body change (`page_rev`; tags are not revisioned).
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
page's versions.

Deleting a page is a **soft delete** (`deleted_at`, undelete); nothing is purged yet, so every query
that follows jobs or links must check it.

## Consequences

- Wrong model output is always recoverable: the worst outcome of an injected or poor result is a
  wrong version, which history can undo.
- Storage grows (versions, stored model runs, originals); `scrap gc` ([](0015-images-in-text-and-gc.md))
  reclaims only provably unused files.
- Because cascades never fire on soft delete, code must not rely on them for trashed pages.
