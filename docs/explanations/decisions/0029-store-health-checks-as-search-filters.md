# 29. Store health checks as search filters; outdated write-ups are the owner's to regenerate

Date: 2026-10-26 (#262)

## Status

Accepted. Stage 2 of the #104 roadmap ("a timer-driven lint pass that only reports"), part of
scrap as an LLM wiki (#263); covers the "Vault lint" gap of #172. Builds on
[](0027-claude-write-ups-of-boards-apart-from-the-text.md) and
[](0028-claude-maintained-topic-pages.md).

## Context

A store that grows by quick captures collects loose ends: pages nothing links to, pages with no
tags, todos nobody has touched for months, the same photo captured twice, `[[links]]` to pages
that are gone, and Claude's derived data (board write-ups, topic syntheses, related pages) left
behind by edits or a prompt change. The owner needs to see them, and Claude's derived data needs
to catch up without a prompt change making every page due at once.

## Decision

- **A finding is a search filter, not a stored report.** Each check is an `is:` or `has:` term:
  `is:orphan`, `is:untagged`, `is:stale`, `is:duplicate`, `has:dangling` and `is:outdated`. They
  are SQL fragments in one module, `store/health.py`, used by search, so a finding is always
  current, works in the PWA's search and MCP `search`, and needs no table, migration or new MCP
  tool. `-` before one excludes, as for any filter.
- **Machine-made pages are left out where a finding would be noise.** Topic pages (Claude's, with
  no tags and an empty body) are never untagged, and a topic with a source in and its sources are
  never orphans. gc's Orphaned assets pages (a capture of source `gc`) are never untagged, stale,
  orphans or duplicates, and a file shared with one, or with a page in the trash, is no
  duplicate. An open todo due today or later is not stale: its due date brings it up.
  A `[[link]]` is any `[[...]]` the server parses as a page link, outside code and not an
  embed; this includes forms the PWA draws as plain text (`[[Some Title]]`), so
  `has:dangling` finds links that don't work. They are found through a SQL
  function `wiki_links` registered on each connection, so a check is one pass over the pages.
- **A Store health screen, counts only.** Settings has **Store health**: each check with its
  count (`GET /api/health`, one `count(*)` a check), a tap running its search. Nothing is
  dismissed: a check that keeps finding a page the owner is happy with is the check to change.
- **One definition of outdated per kind of derived data**, in `store/health.py`, shared with
  what refreshes it: a board write-up (`writeups.OUTDATED`, beside the worker's `DUE`: a board
  image read, or the page's text, title, kind or tags changed, after it, or another prompt
  version; never a version the owner restored), a topic synthesis (the weekly pass's
  `TOPIC_DUE`) and related pages (the nightly pass's `STALE`).
- **`is:outdated` lists only outdated write-ups** (#291): what the owner acts on, with
  Regenerate or `scrap enrich --writeups --outdated`. The current write-up prompt version is
  given to the store by whoever makes it (`Store.prompts`, `enrich.prompt_versions()`), since
  the store sits below the prompts. Related pages and topic syntheses keep their definitions
  for the passes but are no finding: they clear on their own overnight or within the week, and
  as findings they buried the write-ups (right after a write-up is regenerated, its page's
  related picks are older than it).
- **An outdated write-up is the owner's to regenerate.** Only a newly read board photo writes one
  again on its own (as before). An edit to the page, or a new prompt, does not: an edit may be
  small, a write-up is an Opus call, and the owner may prefer the old one. The page's write-up
  carries an `outdated` flag (the same SQL), and its card says quietly "The page (or Claude's
  prompt) has changed since this write-up." beside Regenerate. `scrap enrich --writeups
  --outdated` writes again every outdated one (with `--limit`, `--dry-run`, the budget and the
  pause): how a new prompt is rolled out. The nightly related pass and the weekly topics pass are
  unchanged: related pages and topic syntheses stay automatic, as do summaries (enrich on save).
- **No model-assisted lint call.** Contradictions and open questions are in each topic's
  synthesis, new topics come from weekly discovery, and suggested links from the related pass. A
  separate lint call would repeat them.

## Consequences

- The checks cost no stored state and no Claude spend; the counts are cheap queries.
- A new check is a fragment and a line in `CHECKS` (and its name in the PWA's `checks.ts`), and
  is documented with the other filters and in the MCP `search` description.
- `is:outdated` is only work that waits for the owner. A related pass or topics pass that keeps
  failing does not show in Store health; the passes' own logs and exit status say so. A
  write-up prompt change lists every board until it is rolled out with `--writeups --outdated`.
- No timer, CronJob or chart value changes: the scheduled jobs are as before
  ([](../../reference/scheduled-jobs.md)).
- The checks are word- and link-based. If they prove too weak, semantic search (#53) is the next
  step, and a model-assisted check can be revisited.
