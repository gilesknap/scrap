# 30. The trash is purged after N days

Date: 2026-10-26

## Status

Accepted

## Context

Deleting a page moved it to the trash, and nothing ever emptied it: "nothing deletes a page" was
the promise, in the design, the PWA's docs and the MCP server's instructions. A trashed page kept
its captures, and so its files (gc counts a capture as a use), and all Claude's results and runs.
Done and dead job rows piled up too. The database and the file store grew without bound (#276).

A size report run on a copy of the live store (54 MB database, 226 MB of files, a week after
moving in) found 76 pages in the trash holding 29 files (25 MB) that nothing else used: an eighth
of the file store, after one week. The trash was all under 7 days old, and no job row was finished
more than 7 days ago. The Claude call records were most of the database (`enrich_run`, 1150 rows,
47 MB), which `gc.runDays` already prunes after 30 days.

## Decision

Nightly `scrap gc --delete` purges a page that has been in the trash for more than `--trash-days`
(default 30, at least 1): its row goes, and with it, through the schema's `ON DELETE CASCADE`,
its revisions, captures and their file records, Claude's results, runs and jobs, tags, search
index, write-ups and topic memberships, in one transaction, committed (with the job and run
pruning) before gc reads what is in use: no file is unlinked while it could still roll back. Its files are then
unused, so gc's usual delete takes them in the same run, under its grace period and only after a
recent backup (the backup check of `deploy/scrap-gc` and the chart's CronJob, which run a dry run
without one). A purged page still exists in the backups for the backup retention.

- **A topic page in the trash is never purged.** Its key is the veto that stops discovery making
  the topic again ([](0028-claude-maintained-topic-pages.md)), and the key's row needs its page.
  Kept in the trash, the veto is visible and can be undone.
- **gc's review pages** (Orphaned assets, #124) are purged like any page. The files a review page
  showed, in any revision, that would be orphans again once it is gone are let go with it: their
  file records are taken off the capture still holding them, with that photo's Claude results,
  jobs and runs. Otherwise each would be gathered again onto a new review page every month, and
  deleting the review page would never reclaim their space.
- **Finished jobs**: `job` and `enrich_job` rows done or dead and last changed more than
  `--job-days` ago (default 30) are deleted, but each photo's newest ingest job and each page's
  newest enrich job of a reason are kept: the PWA shows a photo's or a page's state from them, and
  a page's one first related call is known by its job.
- The promise becomes: **nothing deletes a page until it has been in the trash for N days.** The
  server knows N from `SCRAP_TRASH_DAYS` (the chart sets it from `gc.trashDays`, or `off` while its
  gc deletes nothing). The PWA has a Trash screen (Settings) and the MCP `trash` tool lists each
  page's `purge_at`.
- `scrap gc --report` prints the size report: the database by table, the files by use, the trash
  by age, the call records by month and the job rows by state.

The defaults stay 30 days: a month to change one's mind, while the trash's files are reclaimed
every month.

## Consequences

- A page restored within N days comes back whole; after that it is gone, except from backups.
- A dry run counts the pages it would purge and the files that would free, by purging inside a
  transaction it rolls back. It takes the write lock for that moment.
- A file let go with a purged review page is gone from every revision that embedded it: an older
  revision of the page it came from (or of any page) that is restored shows a broken image.
- In a run whose gathering of orphans was interrupted (the review page edited meanwhile), no review
  page is purged; the next run purges it.
- On a single server `SCRAP_TRASH_DAYS` in `ingest.env` is the one setting: the server reads it,
  and `deploy/scrap-gc` passes it to gc as `--trash-days`. Retentions are 1 to 36500 days.
- No migration: purging relies on the cascades already in the schema.
