# 12. Page kinds with flat fields; due date and priority as typed columns

Date: 2026-10-19 (design), 2026-10-20 (kind in the editor), 2026-10-21 (todo fields, #104)

## Status

Accepted

## Context

Pages need light classification (note, todo, read, whiteboard, document) so views and filters work,
without turning scrap into a template engine or a task manager. Thoth, the previous system, supplied
the vocabulary.

## Decision

- `kind` is one of `note` (default and fallback), `todo`, `consume` (decided as "Read"; the PWA
  shows "Later", see the consequences), `memory`,
  `reference`, `whiteboard`, `document`. The PWA offers Note, Todo, Later, Whiteboard and Document;
  the rest stay in the schema until wanted. The list is hard-coded until real use asks otherwise.
- Kind-specific data lives in a **flat JSON `fields` object** (no nulls or nesting), not per-kind
  tables: status (`open`, `in_progress`, `done`, `cancelled`, Thoth's lifecycle) and, for reads, a
  subtype and source link.
- **A due date and priority are typed `page` columns**, not fields, so `due:`/`priority:` filters
  and sorts are indexed SQL. `due` is a calendar day with no time zone; priority is high/medium/low.
  They belong to todos: the API refuses them elsewhere, and a todo turned note keeps them hidden
  rather than losing them. Setting them is not a revision.
- Changing a kind **keeps every field** and adds the new kind's defaults, so a stray tap loses
  nothing. A kind set by capture or in the editor sets `kind_fixed`; ingest sets kind
  only while it is an unfixed `note`, and fields and tags only on the first success. (Tags have
  since become a merge, see the consequences.)
- Deliberately out: recurring tasks, sub-tasks, projects.

## Consequences

- New kinds are code changes, not data migrations; filtering by kind or status is cheap.
- Fields are only as validated as the code that writes them; the schema checks the JSON type only.
- Migration 0005 moved imported `due` and `priority` out of `fields`.
- The `consume` kind shipped in the PWA as "Later", not "Read": `web/src/kinds.ts` names it Later,
  and a search's `kind:` also accepts `later` and `read` (`KIND_NAMES` in `store.py`) beside
  `consume`.
- Tags are no longer set only on the first successful model run. Photo ingest adds its tags to the
  user's on the first reading of the first photo (and on a later one only to a page with none),
  and text enrichment ([](0020-text-enrichment.md)) adds up to five on a page's first reading, on
  capture, on Ask Claude and on backfill. Both mark them in `model_tag`, and neither adds back a tag
  the user took off. Enrichment also makes a link's page a `consume` page, but only while it is an
  unfixed `note`. Kind and tag edits are revisioned by [](0019-kinds-and-tags-editable-with-revisions.md).
