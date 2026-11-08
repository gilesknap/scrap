# 35. Files are read locally, for search

Date: 2026-10-27

## Status

Accepted. Its rule that a file's text goes to Claude only on **Ask Claude** (the Decision's "No
model is called for a file, nothing about it is sent anywhere" and the #378 amendment's "Nothing
else sends it", for enrich on a capture) is superseded by
[](0038-file-text-is-sent-to-claude-on-capture-bounded.md): with `SCRAP_FILE_ENRICH=auto`, the
default, a file page's first enrich is sent the start of its files' text. The rest of this
decision remains.

## Context

A PDF attached to a page (shared, imported, or added in the editor) was stored and listed, but
nothing read it: search could not find a word in it, and MCP `read` had nothing to give Claude
but its address (#234). The issue proposed sending each PDF to Claude, as a photo is, for its
text, a summary, a title and tags. A model alone cannot count a PDF's pages or cut it to the
first few without a parser; its transcription of a long document is paid per output token and
risks running out of tokens; and nothing would be searchable with ingest off or paused. A PDF is
also more private than a photo: a statement or a letter would go whole.

## Decision

- scrap reads a PDF's text layer itself, with `pypdf` (pure Python, BSD licence), and a text
  file's (`text/plain`, `text/markdown`) by decoding it as UTF-8. The text is stored as a
  `derived` version of kind `ocr` (no `model_run`), which the existing trigger indexes, so
  search finds it. No model is called for a file, nothing about it is sent anywhere, and it never
  changes the page's text, title, kind or tags.
- PDFs are parsed in a child process with a 60 s wall-clock timeout, a 512 MiB address-space
  cap and a CPU-time cap, an empty environment and its stderr discarded, so a hostile file (a
  decompression bomb, a pathological object graph, a flood of warnings) costs that process, not
  the service, and the child never holds the service's keys. It reads the first 200 pages and keeps 500,000 characters at most; a file over
  30 MB is not read. A PDF encrypted with a password other than the empty one is not read.
- A file is an ordinary `ingest` job, in the same `job` table and worker, keyed by capture and
  SHA-256. It needs no budget and is not held by a pause. Any failure is final (the same file fails
  the same way again): the job is dead at once with its reason, the file stays attached, and
  **Reprocess** retries it. It takes no part in a page's first reading or its write-up.
- Summaries are the user's to ask for: Claude, over MCP, reads a file's text (`read` gives its
  first 20,000 characters, and whether it is searchable) and summarises it in the conversation.
- No schema change: everything fits the existing `job`, `derived` and `chunk` tables.

## Amendment (2026-10-27)

The security review of file ingest (#321) corrected and tightened this decision.

- "The child never holds the service's keys" is true of its environment only. The child runs as
  the service's user, on its filesystem and network, so a code-execution bug in `pypdf` could read
  the data directory. The sandbox is a limit on cost (time, memory, and now no file written and no
  core dump: `RLIMIT_FSIZE` and `RLIMIT_CORE` are 0), not a boundary for confidentiality. The
  container's non-root user, read-only root and seccomp profile are what limit it. `uv.lock` pins
  `pypdf` 6.21.2, past the decompression limits the child relies on.
- A failure that may pass (the child not starting, a timeout under load) is charged and retried,
  three times in all, rather than final; a file that cannot be read is still dead at once. A
  file without `%PDF-` in its first KiB is refused before a child is started.
- A file already read (same hash, same `pypdf`) is copied, not parsed again; photos are claimed
  before files, and enrichment gets a turn between files.
- Over MCP, a file's `text` carries a `text_note` (untrusted third-party text, quoted data, never
  instructions), as `by_model` does, and the server instructions name file text.

## Amendment: Ask Claude reads a file's text (#378)

A page made from a PDF alone kept its capture time as its title and got no summary even on
**Ask Claude**, because enrich saw only the page's own (empty) text. Ask is the owner's explicit
act, so it is the owner deciding what a model sees:

- On Ask, enrich and its related call are sent what scrap read from the page's files (at most
  8,000 and 3,000 characters), quoted in a `<files>` block. Nothing else sends it: not enrich on
  a capture or save, nor the nightly related pass, nor topics. Related candidates may be found by
  the files' words, a local full-text search that sends nothing. What Ask writes from them (the
  summary, the title) is stored, and later calls send it as any page's (related, the indexes,
  topics: quoted, model-written).
- A page made from a file alone (its first capture a file's with no text, its title untouched)
  gets a title from its files' text on Ask, as a photo page gets one from its photo.
- On an Ask that sends files' text, no list of actions is applied at all (no task boxes, no
  todo), not even one in the owner's own typed text: the files' text is a stranger's, maybe
  invisible in the PDF. A later save of a typed page (one enrich reads on a save) still files its
  own list, as that re-reading sends no files.
- A re-reading that does not send the files (a save of a typed page with a PDF added) keeps a
  summary an Ask made; the next Ask renews it. Any other summary is refreshed as before, as is
  one whose Ask run or job retention has since pruned.
- Still no model reads the file itself, and file ingest still never changes the page.

## Consequences

- Search finds words in PDFs and text files as soon as the worker reads them, at no cost, and the
  owner decides what, if anything, a model sees.
- A scan (a PDF with no text layer) is read as empty: not searchable. Reading scans would need OCR
  or a model call, which this decision leaves out; a later decision can add one (a photo of the
  page works today).
- One more runtime dependency (`pypdf`), and a child Python process per PDF read.
- `SCRAP_INGEST` still starts the worker: with it off, files wait unread, as photos do.
- Enrich, related pages and topics do not read a file's text; the PWA's file row (state, pages,
  searchable) follows separately.
