# What Claude is asked, per page

Four calls, all on the shared queue, pause and daily budget ([](ingest.md)). Photo reading and
the write-up use `SCRAP_VISION_MODEL` (default `claude-opus-5-5`); enrich and related use
`SCRAP_TEXT_MODEL` (default `claude-haiku-5-5`). Ask Claude (`POST /api/pages/{id}/enrich`) runs
enrich, then on a board page the write-up, then related, on any page.

| Page | Photo reading | Enrich | Write-up | Related |
|---|---|---|---|---|
| Typed note, todo or read (MCP `write` too) | — | On capture and on each save, after the debounce: tags (none from a save), summary; a confident list of actions in an unfixed note gets task boxes | — | Once after its first enrich; nightly if changed; Ask |
| Saved link | — | On capture, at once: fetches the address, then title, tags, summary. A save reads it again without fetching | — | Once after its first enrich; nightly if changed; Ask |
| Photo capture of a whiteboard or diagram (filed as a whiteboard) | Per image: kind, description, text (OCR), drawing. From the capture's first image only: title, tags, a to-do list | Skipped (Ask only) | Once all its photos are read, and again when a board image is read later (Reprocess, a new photo); Regenerate; Ask; `scrap enrich --writeups`. Sees the board photos (at most 4), their text and descriptions, title, tags, text and the owner's guidance; links related candidates. Not for a to-do sticky (a list of actions) | Once after its write-up; nightly if changed, a photo is read or the write-up is newer; Ask. Sees the images' text and the write-up |
| Photo capture of a document, handwriting, screenshot or photo | The same, with no drawing | Skipped (Ask only) | — | Once when all of its first photo capture is read; nightly if changed or a photo is read; Ask. Sees the images' text |
| File capture (PDF and the like) | — (PDF summaries: #234) | Skipped (Ask only) | — | Nightly if changed; Ask. Sees title, tags and text only |
| Whiteboard or document page typed, not photographed | — | Skipped (Ask only) | — | Nightly if changed; Ask |

What each call sees. Enrich gets the page's kind, tags, title and text as plain words (at most
12,000 characters), what was read from its images (at most 8,000) and, for a link, the fetched
text. Related gets the page in brief (title, tags, summary, the first 2,000 characters of its text
and 3,000 of its images' text) and an index of up to 150 candidates. The candidates are the pages
sharing the most tags, then a full-text search for 24 of the page's words: title, tags and summary
first, then its images' text, their descriptions, and last its own text. Data is quoted in
`<page>`, `<images>` and `<fetched>` blocks, and any such tag inside the data has its `<` sent as
`&lt;`, so the data cannot end its block. A photo page usually has no enrich summary (Ask can add
one); a board's write-up gives it one. The write-up gets the board photos themselves (at most 4),
what was read from them (at most 12,000 characters), the page's title, tags and text (at most
6,000), the owner's guidance in a `<guidance>` block and the related call's index; it cites pages
by number, and scrap makes those `[[slug]]` links ({ref}`ingest-writeup`).

Imports are not read as text unless `scrap enrich --backfill` queues them (their first enrich then
queues the related call). Their photos are read only with `scrap import --ingest`.
