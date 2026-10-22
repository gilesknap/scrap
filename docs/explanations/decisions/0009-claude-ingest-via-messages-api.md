# 9. Claude ingest: Messages API, no tools, one structured call per photo

Date: 2026-10-19 (design rounds 1-3), built 2026-10-19/20

## Status

Accepted. Supersedes the first design's `claude -p` backend, Read tool, and separate
`extract`/`redraw`/`summarise` jobs. Extended by [](0020-text-enrichment.md): notes, todos, reads
and saved links are now also sent to Claude (a small text model, with a link fetched first), so
"photos only" below describes this ADR's photo ingest, not all use of the API.
Amended by [](0019-ingest-on-a-claude-seat-through-claude-p.md): a locked-down `claude -p`, with
no tools, is a second backend for a Claude seat.

## Context

The first design had headless `claude -p` on a subscription login, with a Read tool for images and
separate extract, redraw and summarise jobs. An experiment on real whiteboards showed one vision
call can return everything, and the CLI route needs a tool grant and runs next to the service's own
credentials, with unclear terms for unattended use.

## Decision

- The `anthropic` SDK, Messages API only, no `tools`, key from a mode-600 env file, SDK debug logging
  off. `complete()` is the seam if another backend is ever wanted.
- **One `ingest` job per distinct image of a photo capture**, producing text (OCR), description,
  kind, title, tags and drawing elements in a single schema-constrained response. Photos only in
  M2; URL fetching, notes and files are not ingested.
- Default model `claude-opus-5-5` (best on handwriting in the experiment); `effort` set explicitly
  and recorded. Claude gets a JPEG made server-side (orientation applied, HEIC converted), scaled
  to the high-resolution cap with `oversized_image: error` so the API never rescales silently and
  drawing coordinates are in sent pixels.
- The schema uses only the documented structured-output subset (flat element objects, no tuples or
  unions); `id` is required because the model dropped optional ids and so every arrow binding.
- Every call is stored as a `model_run` (request with image references, response blocks as
  returned, usage, cost, prompt version), so later discussion (M4) or MCP can resume from what the
  model saw and said. `prompt_version` hashes prompt and schema.
- The model sees data only: no tools, no network. Output is sanitised, and the model can change
  only versions, a provisional title, empty tags and an unfixed `note` kind.
- Ingest is off (`SCRAP_INGEST`) until spend control is configured.

## Consequences

- Cost is predictable: about $0.03-0.06 a board.
- One worker thread runs jobs (11-55 s each); no asyncio, no second process.
- Stored runs cost 10-50 KB each and cannot be deleted while a version uses them.
- Run pruning and refine/chat (M4) are deferred. Non-photo ingest was deferred here and is now
  [](0020-text-enrichment.md).
- A photo's tags are no longer only for an empty page: they join the user's tags on the first
  reading of the capture's first photo (a later reading adds them only to a page with none), and
  are marked in `model_tag` so a tag the user takes off stays off.
