# 15. Images are embedded in the page text; `scrap gc` is conservative

Date: 2026-10-20 (#48, #57, #78, #103)

## Status

Accepted; amended by [](0030-trash-purged-after-n-days.md): captures, and their files, are now
purged with their page once it has been in the trash for N days; amended by #403: a capture's text
may place its own uploads (below)

## Context

Pages are Markdown, and a photo should appear where the text puts it. Files are content-addressed
and shared, so deleting one safely is harder than deleting a row.

## Decision

- A photo capture's page text is its text followed by one `![](/api/blobs/<sha>/preview?size=2048)`
  per image. From then on the text is the user's: ingest never edits it. A line of images becomes
  figures (viewer, Download, Ask Claude); images elsewhere stay inline. Files not embedded (PDFs,
  older pages) are listed under the text. Export points text at the exported files.
- Amended (#403): a capture's text may place its own uploads with tokens, `⟦image N⟧` or
  `⟦file N⟧` (N the upload's place in the request), when the request asks (`place=1`, the
  composer's; other clients' text is never read for tokens). The server puts that upload's embed there, or
  for a PDF or text file a `[name](/api/blobs/<sha>)` link (its row is then drawn in place, not
  listed under the text). Uploads with no token are added as before. The phone cannot write the
  address itself: a photo's bytes, and so its SHA-256, are final only once it is queued.
- The editor warns on Save when an embed of a stored file is removed, naming how many other pages
  still show it.
- `scrap gc` deletes only files nothing refers to: not any page's text (the trash's too, found by
  one function, `store.body_refs`, deliberately *not* the Markdown parser, since gc deletes whatever
  it misses), capture, derived row, job or model run. Files younger than 24 hours are skipped; the
  references are reread in a write transaction before deleting; each file is renamed aside and
  its age rechecked; a run interrupted mid-way is reconciled by the next. On a single server a nightly timer runs it
  after backup (the Helm chart has no gc job).

## Consequences

- Captures are never purged, so most files live on; gc mostly removes abandoned uploads and orphans.
- Old revisions do not count as references.
- A manual gc takes no lock and can race the nightly run harmlessly.
- `scrap gc` is a **dry run unless `--delete`** is given (`--dry-run` forces it): it only counts
  what it would remove. `--grace-hours` (default 24) sets the age below which a file is kept.
- A capture's file that no page shows any more is never deleted: `scrap gc --delete` gathers it
  onto the month's *Orphaned assets YYYY-MM* todo page for the user to review (issue #124), worked
  out from page text and revisions alone, so a second run adds nothing.
- It also prunes the `model_run` and `enrich_run` records (issue #151): those older than
  `--run-days` (default 30) that nothing refers to and that are not the latest for their page or
  photo, so the stored prompts and responses do not grow for ever.
- The nightly timer's script (`deploy/scrap-gc`) takes the lock it shares with `scrap-backup`,
  so the two never run at once, and passes `--delete` only if a backup run directory younger than
  26 hours holding the `COMPLETE` marker (written after an integrity check) exists in the
  backups folder. Without one it counts only, says so, and exits non-zero.
