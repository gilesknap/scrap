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
  before. Only new reads trigger it: a file read before this change, or while the setting was
  `ask`, stays Ask only (no backfill).
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
  stays dead with its reason and **Reprocess**. **Reprocess** of a file on a page that has no
  enrichment yet counts as a new read, so with `auto` it then queues the page's enrich.
