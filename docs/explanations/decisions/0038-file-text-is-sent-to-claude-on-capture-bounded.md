# 38. File text is sent to Claude on capture, bounded

Date: 2026-10-28 (#402)

## Status

Accepted. Supersedes the "explicit Ask only" rule of
[](0035-files-are-read-locally-for-search.md) (a file's text goes to no model unless the owner
presses **Ask Claude**) and its #378 amendment's clause "Nothing else sends it" for enrich on a
capture. The rest of ADR 35 stands: local reading with `pypdf` in a sandboxed child, local search,
failures dead with a reason and **Reprocess**, and no list of actions from a file's text.

## Context

A shared PDF stayed titled with its capture time, untagged and unsummarised until the owner pressed
**Ask Claude**: share and forget did not work for files, as it does for photos and links. ADR 35
kept files from Claude for four reasons. Three were about sending the PDF itself (a model cannot
cut a PDF to its first pages, long transcriptions cost output tokens, nothing searchable with
ingest off); they do not apply to sending text scrap has already read locally and cut. The fourth,
privacy (a statement or letter would go whole), is met by sending only the start of the text, by
a setting that keeps the old rule, and by the fact that photos of letters and documents already
go to Claude whole on capture. Prompt injection from a stranger's PDF was already handled for Ask
(#378): the text is quoted, and an enrich that sends it applies no actions.

## Decision

- **When.** With `SCRAP_FILE_ENRICH=auto` (the default), once file ingest has read the last file
  of a page's first capture, and that capture is a file capture (a PDF or text file sent with no
  photo, `roles.FILE_FIRST`), not an import, the page has no enrichment yet and at least 200
  characters were read from that capture's files, the page gets an enrich job (reason `capture`).
  A file added later to any page queues nothing, so a typed page with a PDF added behaves as
  before. Only the capture's own file jobs trigger it (those made with it, in its transaction:
  `job.created_at` is the capture's `received_at`; a charged failure retried is the same job).
  A job **Reprocess** or **Retry** queues later never does, so a file read before this change,
  or while the setting was `ask`, or that failed and was retried, stays Ask only (no backfill).
- **Once.** The job makes no call when the page has an enrichment another job made (an Ask that
  ran meanwhile wins and is not sent again), when the setting has become `ask`, or when under 200
  characters are left to send.
- **What is sent.** Text, never the file: at most the first 4,000 characters of the page's files'
  text to enrich and 1,500 to its first related call, which runs in the same job (Ask keeps its
  8,000 and 3,000). The limits are constants (`enrich.AUTO_FILES`, `enrich.AUTO_RELATED_FILES`).
  The nightly related pass, write-ups and topics still never send a file's text.
- **#378's safeguards hold unchanged.** The text is quoted in a `<files>` block with any delimiter
  tag's `<` sent as `&lt;`; an enrich that sends files' text applies no list of actions (no task
  boxes, no todo); file text never changes the page's text. Only tags, the summary, a title (a
  page made from a file alone with its title untouched, `FILE_UNTITLED`) and related pages come
  back. A file page with a note typed at capture keeps its title.
- **The setting.** `SCRAP_FILE_ENRICH` is `auto` or `ask` (case-insensitive; empty is unset);
  any other value stops the worker starting. `ask` is the old rule: nothing is sent unasked.
  There is no `off`: Ask is the owner's explicit act and always works, and `SCRAP_ENRICH=off`
  already stops every text call, Ask's included. The worker checks the setting again before the
  call, so a job queued before a change to `ask` makes no call.
- **Model, budget, pause.** It is an ordinary enrich job: `SCRAP_TEXT_MODEL` (a Haiku-class model
  by default), the shared daily budget (over it, the job waits for the next day, with no failure)
  and the shared pause; nothing is queued with `SCRAP_INGEST` or `SCRAP_ENRICH` off. Reading the
  file itself still needs no budget and is not held by a pause.
- **Left out.** A per-page "don't send" flag and a separate file budget (no existing mechanism to
  reuse; the setting and the shared budget cover them for now), a "looks sensitive" pattern skip
  (its false positives and negatives were judged worse than a clear global switch), and a PWA
  toggle (environment only).
- No schema change: `capture` is an existing enrich job reason.

## Consequences

- A shared text-layer PDF or text file is titled, tagged, summarised and related with no manual
  step, at a few thousand input tokens on the text model.
- The start of every new file page's text leaves the host by default. An owner who keeps
  sensitive documents in scrap sets `SCRAP_FILE_ENRICH=ask`.
- A long document is summarised from its first 4,000 characters (about three pages); Ask reads
  twice as much.
- A scan, a password-protected, corrupt or over-30 MB file is not read, so nothing is sent: it
  stays dead with its reason and **Reprocess**. A Reprocess that then reads it sends nothing:
  **Ask Claude** does.
- If its related call fails with a charged error, the retry sends the enrich call (with the same
  4,000 characters) again before related, as Ask's retry does.
- Known limitation: one enrich job is queued per page, and a write-up queued at the same time
  takes over a queued file page reading (or keeps its place against one), so that page gets no
  automatic summary; **Ask Claude** gives one. It needs a photo read as a board added to a file
  page while its files are being read.
- Known limitation: if a capture's dead file is **Reprocess**ed while another file from that
  capture is still being read, the page gets no automatic reading when that other file finishes
  (it fails safe: nothing is sent); **Ask Claude** gives one.
- If the job is held by a pause or the budget and another file is added to the page meanwhile,
  that file's text is sent too, still within the 4,000 and 1,500 character limits and quoted.
