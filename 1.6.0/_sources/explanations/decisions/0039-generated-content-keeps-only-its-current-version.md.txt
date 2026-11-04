# 39. Generated content keeps only its current version

Date: 2026-10-28 (#425, #413)

## Status

Accepted. Partly supersedes [](0004-originals-kept-everything-else-derived.md) (derived data is
append-only) for a model's readings of photos and files,
[](0027-claude-write-ups-of-boards-apart-from-the-text.md) (versioned write-ups, **Restore**) and
[](0028-claude-maintained-topic-pages.md) (a synthesis restores like a write-up). ADR 11, a
drawing's versions, History and **Restore**, is unchanged.

## Context

A board's write-up, a topic's synthesis and a model's reading of a photo or file (its OCR text and
description) were each kept as numbered versions, the older ones superseded by triggers. Nobody
could see the readings' history, and the write-ups' was a **Versions** fold with **Restore**.
That history cost a table with immutability triggers, a second API, a fold in the PWA, a
`restored_from` exemption in three outdated checks, and large `model_run` payloads that retention
had to keep because an old row pointed at them. It bought little: a bad write-up is mended with
guidance and **Regenerate**, and a bad reading by **Reprocess**. The owner has no use for the old
generated text. The history of what a person wrote (`page_rev`, `page_meta_rev`,
`page_trash_rev`) and of a drawing is a different matter and stays.

## Decision

- **Write-ups and syntheses.** `writeup` holds one row per page (`page_id` is its primary key).
  Regenerate, and every write-up or synthesis the worker makes, overwrites it in place
  (`INSERT ... ON CONFLICT (page_id) DO UPDATE`), with its producer, run, prompt version, summary,
  text, the guidance it was written with and its time. `writeup_guidance` is unchanged.
- **Readings.** `put_derived` deletes the page's last row of that photo and kind (`ocr` or
  `description`) before it inserts the new one. The reading's chunk goes with it (`ON DELETE
  CASCADE`), and the search entry through the `chunk_ad` trigger. Its version number goes on
  counting, so a first reading is still version 1.
- **Drawings keep their versions.** `derived` kind `excalidraw` is untouched: saves, Claude's
  redraws, a redraw kept non-current when the owner chose **Keep mine**, History and **Restore**
  (viewer, `drawing.py`, MCP `base_version`). Drawings are not folded into `page_rev`: a drawing
  belongs to a photo, not a page, and `page_rev.rev` is the page text's edit token, so a drawing
  save would turn open editors away with a 409.
- **Removed.** `GET .../writeup/versions`, `POST .../writeup/restore`, `StaleWriteupError`, the
  PWA **Versions** fold, **Restore** button and `v2 · restored from v1` byline, the
  `restored_from` and `superseded_at` clauses, and `version` in `read`'s write-up.
- **Outdated.** A write-up or synthesis is no longer exempt from `is:outdated` or the weekly topic
  pass because the owner restored it: there is nothing to restore.
- **Migration 0019.** Deletes superseded write-ups, drops the three triggers and two indexes,
  rebuilds `writeup` (SQLite cannot drop a column that is in a `UNIQUE` constraint) and deletes
  superseded `ocr` and `description` rows. A superseded row has no chunk already, so search is
  unchanged. No backup or check of the old versions is needed: the owner has no concern for them.

## Consequences

- A bad Regenerate cannot be undone. Write guidance and Regenerate again.
- A restored synthesis that has an old prompt version is remade by the next weekly pass.
- Retention no longer keeps a `model_run` for a superseded reading: only for the current one, a
  drawing version or a write-up.
- Roughly 400 fewer lines, and one write-up row per page makes the queries plain.
- The migration is irreversible, which is why 1.0 holds only the current generated content.
