# 8. Search is SQLite FTS5 with a shared query syntax; embeddings are deferred

Date: 2026-10-20 (the original hybrid plan: 2026-10-19)

## Status

Accepted. Supersedes the hybrid-search plan in the first design.

## Context

The v0 design called for FTS5 (BM25) plus sqlite-vec nearest-neighbour search with local fastembed
embeddings, merged by reciprocal rank fusion. In practice the first milestones shipped without
embeddings: the corpus is small, exact words and filters answered real use, and a local model adds
an image dependency and a re-embed-everything migration story. (`sqlite-vec` and `fastembed` are not
dependencies today.)

## Decision

- Search is FTS5 with `porter unicode61`. A page's own chunk has separate columns for title, tags,
  summary and text (migration 0003) so ranking can weigh them: pages with every word in the title
  first, then title/tags/summary, then bm25 with column weights 10/5/3/1. Every word matches as a
  prefix.
- A derived version's text is indexed as its own chunk while current (triggers), so OCR and image
  descriptions are searchable; pixels and raw Excalidraw JSON are not.
- One query parser (`query.py`) serves the PWA's search box and MCP: `kind:`, `tag:`, `is:`,
  `has:`, `image:`, `due:`, `priority:`, `before:`/`after:` ranges, `date:`, quoted phrases, negation and `sort:`.
  Facets and tag browsing come from the same code. The PWA has one Search screen: an empty box lists
  everything newest first.
- The index is a cache and a numbered migration with an `AFTER` hook (`store.AFTER`) rebuilds it;
  there is no `reindex` command.

  > Superseded in part by [ADR 37](0037-one-baseline-schema-for-1-0.md): `store.AFTER` is deleted; the baseline carries the full-text index rebuild.

## Consequences

- Fast, explainable, no model download. No semantic recall: "that thing about gardens" will not find
  a page that never says garden.
- The first design planned sqlite-vec, fastembed and reciprocal rank fusion; this ADR replaced
  that plan, and [the design page](../design.md) now describes scrap as built (FTS5 only). Related
  pages ([](0020-text-enrichment.md)) are found by shared tags and full-text search, not
  embeddings.
- The `chunk_vec` design is still available. If embeddings return, the plan is: one model at a time,
  embed first without a lock, then swap `chunk_vec` in one short write transaction.
