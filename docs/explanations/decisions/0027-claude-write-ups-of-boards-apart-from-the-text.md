# 27. Claude's write-ups of boards, apart from the text

Date: 2026-10-25 (#256, migration 12)

## Status

Accepted. Builds on [](0020-text-enrichment.md) (the enrich queue, related pages) and
[](0004-originals-kept-everything-else-derived.md) (everything a model makes is derived). Part
of scrap as an LLM wiki with a strict human/LLM split (#263). Partly superseded by
[](0039-generated-content-keeps-only-its-current-version.md): a write-up keeps only its current
version, so there is no Versions list or Restore.

## Context

A whiteboard or diagram photo gets one photo call: its kind, a title, tags, a 1-3 sentence
description, its text and a drawing. That says what is on the board, not what it means. Boards
imported from Thoth carry long explanations written into their text by Thoth's curate pass,
richer than anything scrap writes, but they are in the body, which is the owner's. The real
source of a board is its photo, so an explanation of it is derived, regenerable data, and the
owner should be able to steer it.

## Decision

- **A write-up per board page**, not per image: one Opus call (`SCRAP_VISION_MODEL`) for a page
  with a `whiteboard` or `diagram` image (the photo call's image kind) that the photo call did not
  judge a list of actions. It sees the board photos themselves (at most 4, the JPEGs photo ingest
  sent), what was read from them, the page's title, tags and text as context, the owner's
  guidance, and the related candidates as a numbered index. It returns a short `summary` and
  Markdown `text`: overview, structure, decisions, open questions, related pages, faithful to
  the board, with uncertain readings kept as (?).
- **Links by number.** The model cites a candidate as `[[n]]`; scrap rewrites each valid number to
  `[[slug]]` and drops any other link, so a write-up cannot link a page that does not exist.
- **Stored apart from the text, versioned.** A new table, `writeup`, keyed by page: `version`,
  `producer`, `run_id` (its `enrich_run`), `prompt_version`, `summary`, `text`, the `guidance` it
  was written with, `restored_from`, `superseded_at`, `created_at`. One current version
  (a partial unique index), the last superseded by a trigger, versions never changed (triggers).
  A regeneration adds a version; Restore copies an old one as a new current version, as drawings
  do. Nobody edits a write-up, and it is not in page revisions.
- **Steering.** An optional guidance note per page, set by the owner (`writeup_guidance`, the API
  and the PWA), is given to the next write-up and kept with it: the seed of discussing a
  write-up with the model.
- **When.** An enrich job of a new reason, `writeup`, queued when photo ingest has read all of a
  board page's photos and a board image was read since its last write-up (first reading,
  Reprocess, a new photo), with enrich on. On a board page the first related call comes after
  the write-up, so related sees it; other photo pages keep the call at the end of photo ingest.
  Ask Claude on a board page writes one before picking related pages; Regenerate queues one;
  `scrap enrich --writeups` writes them for board pages with none (the backfill), with the
  related pass's pause and budget rules.
- **Where it counts.** Its summary is the page's model summary (before enrich's), its text is
  indexed for search, its links show in Related both ways (`via: writeup`), and a write-up newer
  than a page's last related picks makes the page stale for the nightly pass. MCP `read` returns
  it as `by_model.writeup`. The PWA shows it in a separate, folding "Claude's write-up" section,
  marked as Claude's tags are (they carry ✦).
- **Migration 12** rebuilds `enrich_job` for its reason `CHECK` (as migration 11 did, keeping its
  rows and the runs' `job_id`, and skipping the rebuild if the table takes `writeup` already) and
  adds the two tables if missing.

## Consequences

- More leaves the machine: the board photos go to the Claude API a second time, with the page's
  text and the candidate index. A write-up costs roughly $0.06 to $0.20 at Opus prices, from the
  shared daily budget; boards are few.
- The body stays the owner's: the Thoth prose on imported boards can be swept out (#257) once
  their write-ups exist (`scrap enrich --writeups`, then `scrap enrich --related`).
- A write-up is as wrong as the model is. It is labelled as Claude's wherever it shows, kept as
  data, and the owner can regenerate it, steer it or restore an earlier one.
- A to-do sticky gets no write-up. A page reprocessed into another kind keeps its write-ups as
  history, but they are no longer shown, searched, linked or its summary (and it cannot be
  regenerated: it has no board).
- To roll back to 0.6.0 (which refuses schema 12), with scrap stopped, run:

  > Superseded in part by [ADR 37](0037-one-baseline-schema-for-1-0.md): this rollback no longer works. Migrations 0001 to 0018 are folded into the baseline and 1.0 refuses a store below schema 18, so `user_version` cannot be set back to 11. Go back by restoring a backup with a release that accepts it.

  ```sql
  PRAGMA user_version = 11;
  DELETE FROM enrich_job WHERE reason = 'writeup' AND state IN ('queued', 'running');
  DROP TABLE writeup;
  DROP TABLE writeup_guidance;
  ```

  The `DELETE` matters because older code would run a `writeup` job as a full enrich, and its
  start-up recovery puts a `running` one back in the queue. The tables must go because 0.6.0's
  `scrap gc` does not know that `writeup.run_id` refers to an `enrich_run`, so pruning that run
  would fail on the foreign key (within its 30 days). The write-ups are lost with them; the
  search chunks made from them go when their pages are indexed again. Upgrading again is safe,
  and `scrap enrich --writeups` writes them again.

## Amendment: on request for any page with an image (#453)

A write-up can also be asked for on **any page with an image**, not only a board: a screenshot of a
live readout is classed `screenshot`, so it never got one. It is opt-in: the owner presses
Generate on the page's Claude card, or asks Claude to call the MCP `writeup` tool (which can set
guidance too). Nothing queues one on its own for these pages, and Ask does not write them up; boards
are written up automatically as before. A page whose images are all lists of actions, or not yet
read, cannot have one.

- Eligibility is `roles.HAS_IMAGE`: a current photo reading of any kind that is not a list of
  actions. `writeup_type` says `image` for such a page that is not a board or topic.
- Such a write-up is made with its own prompt, `prompts/writeup-readout.md`: record readings and
  states faithfully (values with units, per-item status, the capture date, uncertain readings kept
  as (?)). All the page's images are sent (at most 4), with when each was received. A board keeps
  the board prompt.
- No schema change. A write-up made on request is told by its `prompt_version`
  (`writeup-readout@...`, `roles.READOUT_PREFIX`), so a board page's stale write-up on a page now read
  as another kind stays unseen, as before. It is shown, searched, linked and the page's summary like
  a board's, but never flagged outdated (only a board's is), and the weekly and `--writeups` passes
  leave it alone. Regenerate remakes it.
