# 15. Images are embedded in the page text; `scrap gc` is conservative

Date: 2026-10-20 (#48, #57, #78, #103)

## Status

Accepted

## Context

Pages are Markdown, and a photo should appear where the text puts it. Files are content-addressed
and shared, so deleting one safely is harder than deleting a row.

## Decision

- A photo capture's page text is its text followed by one `![](/api/blobs/<sha>/preview?size=2048)`
  per image. From then on the text is the user's: ingest never edits it. A line of images becomes
  figures (viewer, Download, Ask Claude); images elsewhere stay inline. Files not embedded (PDFs,
  older pages) are listed under the text. Export points text at the exported files.
- The editor warns on Save when an embed of a stored file is removed, naming how many other pages
  still show it.
- `scrap gc` deletes only files nothing refers to: not any page's text (the trash's too, found by
  one function, `store.body_refs`, deliberately *not* the Markdown parser, since gc deletes whatever
  it misses), capture, derived row, job or model run. Files younger than 24 hours are skipped; the
  references are reread in a write transaction before deleting; each file is renamed aside and
  its age rechecked; a run interrupted mid-way is reconciled by the next. A nightly timer runs it
  after backup.

## Consequences

- Captures are never purged, so most files live on; gc mostly removes abandoned uploads and orphans.
- Old revisions do not count as references.
- A manual gc takes no lock and can race the nightly run harmlessly.
