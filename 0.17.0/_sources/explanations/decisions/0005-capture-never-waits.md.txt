# 5. Capture never waits: client-minted ids, an offline queue, no LLM on the save path

Date: 2026-10-19

## Status

Accepted

## Context

The main use is a phone in a hurry: snap a whiteboard and put it away, often with poor signal. Any
dependency on a model, the network or the server being up would make people stop capturing.

## Decision

- The client mints a ULID per capture. It is the **retry key**: `POST /api/captures` with a known id
  returns `200` instead of inserting twice.
- The PWA saves to IndexedDB first, shows the capture as *queued*, uploads in the background and
  deletes the local copy only on success, retrying with backoff and on the next open. A nudge that
  finds the queue's lock taken waits for it and then flushes.
- On the server, saving is a file write plus one short `BEGIN IMMEDIATE` transaction (blobs, page,
  rev 1, capture, jobs). **No LLM call is on this path**; the note or title is searchable even if
  Claude is down. Everything slow runs later as a job.
- One capture is one page. Merging and cross-linking come later, by hand or through MCP.
- Android's share sheet is a `share_target`; the service worker queues it like any capture, with a
  server `POST /share` as fallback. iOS has no equivalent (a Shortcut could post to the API).

## Consequences

- A capture is never lost to the upload limit, a crash or a dropped connection, and double taps are
  idempotent.
- Provisional titles (first line, else URL, else device date) exist until ingest improves them.
- No Background Sync yet (deferred), so the queue drains only while the app is open or shown.
