# 17. Import from a Thoth vault goes through `Store` and is idempotent

Date: 2026-10-20 (#45, #47)

## Status

Accepted, then superseded in practice: the importer (`scrap import`, `importer/`) was removed once the
Thoth migration was done (#413). Git history keeps it. A general Markdown import and export is
tracked in #417.

## Context

scrap succeeds an earlier Markdown vault (Thoth). Pages, dates, kinds, fields, tags and images had to
come across without copying rows directly into tables and leaving revisions or the index
inconsistent.

## Decision

- `scrap import` reads a vault and writes through `Store`, so revisions, chunks and the FTS index
  stay consistent.
- Each page keeps the vault's dates (its `created_at`, `updated_at` and revision 1), fixed kind,
  fields and tags. Its capture has source `import`, with the vault file as text (so ingest will not
  retitle it) and its images (PDFs in a second `file` capture). Dates alone become noon UTC.
- The capture id is derived from the page's path, so reruns skip pages already imported and never
  update them.
- Links between pages become `[[slug|label]]`; images become the standard embed form. Links and
  images are found by the Markdown parse ([](0014-markdown-parsed-by-a-library-on-both-sides.md)),
  never inside code.
- Importer inputs are treated as untrusted: bad dates, symlinks, ambiguous names, fences and
  limits are handled and the plan reports lines it cannot map.
- Thoth's `urgent` priority becomes `high`.

## Consequences

- An import cannot refresh pages; edits in either place after the first run are not merged.
- Migration paths for other tools would reuse the same `Store` route.
