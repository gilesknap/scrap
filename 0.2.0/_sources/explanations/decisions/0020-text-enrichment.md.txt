# 20. Text enrichment: Claude tags, summarises and relates text pages, apart from the text

Date: 2026-10-22 (#85, migration 9)

## Status

Accepted. Extends [](0009-claude-ingest-via-messages-api.md), which sent only photos to Claude,
and shares the queue pause and daily budget of
[](0010-job-queue-pauses-instead-of-failing.md).

## Context

Only photo pages were read by Claude, so a note, a todo or a saved link had whatever tags its owner
typed, and no summary. Finding things (see [](0008-search-fts5-only-for-now.md)) and the tag
vocabulary suffered for it. Embeddings were still deferred, so any answer to "what else is like
this" had to come from tags and words. A saved link is the awkward case: its page holds only a
web address, and fetching an address a user saved is a server-side request to something
untrusted.

## Decision

- A second job kind, `enrich` (`enrich.py`), for notes, todos, reads and saved links. It runs on
  the ingest worker's thread, whenever there is no photo job to run, so there is still no second
  process. It is on when ingest is on (`SCRAP_INGEST`) unless `SCRAP_ENRICH=off`.
- One tool-less, schema-checked Messages API call per page, on a small text model
  (`SCRAP_TEXT_MODEL`, default `claude-haiku-5-5`; `SCRAP_TEXT_EFFORT`, default `low`). It returns
  `tags`, a `summary` and, for a saved link, a `title`. The prompt lists the tags already in use,
  most used first, and asks for those; the page and anything fetched are data, and the prompt says
  to follow nothing written in them.
- **Related pages are a call of their own.** `relate` gives Claude a numbered index of at most 150
  candidate pages, chosen by shared tags and then full-text search (`enrich.CANDIDATES`, swappable;
  not embeddings), and it answers with index numbers, so it cannot name a page that does not exist.
  It runs on **Ask Claude** (`POST /api/pages/{id}/enrich`) and in a nightly pass,
  `scrap enrich --related`, for each page changed since its last picks (`--all`: every page).
  Related shows both ways, so an older page learns of a newer one that picked it without a call of
  its own.
- **Triggers.** A note or link capture queues a job (a link at once, a note after
  `SCRAP_ENRICH_DEBOUNCE` seconds, default 60). A save of a page's title or text moves its one
  queued job that far ahead again, so a burst of edits makes one call. A save only refreshes the
  summary: it adds no tags. Tag edits alone queue nothing. `scrap enrich --backfill` queues every
  untagged page Claude has not read, by hand only.
- **Links are fetched safely and only for this** (`fetch.py`): http and https on ports 80 and 443;
  every address the host resolves to must be public, checked again at each redirect, and the
  connection goes to the address that was checked; a size limit, a 20 s deadline for the whole
  fetch, no cookies, credentials or proxy; only HTML and plain text. A failed fetch is not a failed
  job: the page is still tagged from what is known.
- **The user wins, and the text is never edited.** What Claude adds is stored apart from the page
  (migration 9): `enrichment` (summary, fetched address and title), `model_tag` (the tags Claude
  added, `on`, and `off` once the user removes one, after which it never comes back), `related`
  (picks in order), with every call kept in `enrich_run` as `model_run` is for photos (the fetched
  text is not kept, only its length and hash). At most five tags are added, at most two of them
  not already in use, within a page's 64. A link's title replaces the provisional one only while
  the title is still the address as captured; the kind becomes `consume` only while the page is an
  unfixed `note`.
- **Failures and money follow ADR 0010.** Enrich jobs share the queue pause and the daily budget
  (`SCRAP_BUDGET_DAY_USD`): `spent_today` sums `model_run` and `enrich_run`. Outage, credit, auth
  and budget pause the queue and refund the job; any other failure is charged and retried in 10
  minutes (invalid output at once), dead on the third. `scrap enrich --related` checks the pause
  and the budget before each call and stops, exiting non-zero, at either.
- On a single server `deploy/scrap-enrich-related.timer` runs the pass nightly in the service's
  container (`podman exec scrap scrap enrich --related`), after the backup. `install.sh` enables it
  if the image has the command. With ingest or enrich off, or no API key, the command says so and
  exits 0. The Helm chart has no such job.
- On a Claude seat with no API key, enrichment runs through `claude -p` instead: see
  [](0021-ingest-on-a-claude-seat-through-claude-p.md).

## Consequences

- Text now leaves the machine for the Claude API (the page's text, up to 12,000 characters, the
  tag vocabulary, and a fetched page's text), where [](0009-claude-ingest-via-messages-api.md)
  sent photos only. Turning it off is `SCRAP_ENRICH=off`, with photo ingest still on.
- The daily budget is shared with photos: when text calls (a backfill, say) use it up, the queue
  pauses until UTC midnight for photos too.
- Tags can now be set by Claude on text pages, so a page may have tags its owner never typed. They
  are marked in `model_tag`, are not revisions ([](0019-kinds-and-tags-editable-with-revisions.md)),
  and MCP `read` returns them separately as `by_model`.
- Related pages come from tags and words, not meaning; if they prove too weak, embeddings (#53)
  would replace `enrich.CANDIDATES`.
- The nightly pass runs in a process of its own (not the worker's thread), so it shares the worker's
  queue pause and spend only through the database.
- Migration 9 adds tables only (`IF NOT EXISTS`), so an older scrap still runs on a database with
  `user_version` set back to 8.
- The design and prompts are in [](../ingest.md), under "Enrich".
