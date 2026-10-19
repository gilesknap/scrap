# scrap design

Status: design stage. It keeps the ideas of an earlier, much larger system (classified pages,
semantic recall with cited sources, MCP tools for Claude) and drops its machinery (a git-synced
Markdown vault, a chat-bot daemon, a stack of paid-API integrations).

## Principles

1. **Tiny.** One process, one database file, one folder of files. If a feature needs a second
   service, it waits.
2. **Off the shelf.** Claude does the reading and writing that needs judgement. SQLite does storage
   and search. Tailscale does networking and identity. Excalidraw does drawings. scrap is the glue.
3. **Originals are kept, everything else is derived** and can be regenerated. The search index is
   disposable and rebuilt with one command.
4. **Capture never waits.** Saving is a file write and a few row inserts; anything slow runs later
   in a background job.
5. **Claude reasons, the PWA shows.** Claude (over MCP) is for asking and writing; the PWA is for
   capturing and looking. Answers link into the PWA.

## v0 scope

- **One Python process.** FastAPI serves the built PWA, its JSON API and an MCP server (streamable
  HTTP). One worker thread runs the jobs: extract, redraw, summarise, index.
- **Storage.** SQLite in WAL mode and a `files/` folder keyed by SHA-256, on one persistent volume.
  Backup is a SQLite online backup plus a copy of `files/`.
- **Search.** An FTS5 (BM25) query and a sqlite-vec nearest-neighbour query each return ranked
  chunks; reciprocal rank fusion (`sum(1 / (60 + rank))`) merges them and hits are grouped by page.
- **Embeddings.** Local, through fastembed (ONNX on CPU, arm64 and amd64). Default
  `BAAI/bge-small-en-v1.5` (384 dimensions); `nomic-embed-text` (768) if recall is poor.
- **Access.** Tailscale Serve is the only way in; Funnel stays off. The service binds to
  `127.0.0.1` in its pod, so only Serve (in a sidecar) reaches it. No login code.
- **Deployment.** A multi-arch image on a home k3s cluster (ARM and x86 nodes), with a persistent
  volume and a Tailscale sidecar.

**One capture is one page.** Each capture creates its own page at once, with a provisional title
(first line of a note, the URL, or the photo's date). Background jobs then fill in a better
title, a summary and tags. Merging and cross-linking pages is later, by hand or through MCP
`write`. Ingest stays a fixed pipeline with no search-then-decide loop, and every capture is
searchable once indexed.

## Data model

The source of truth is **captures** (what arrived), **blobs** (the bytes) and **pages** (what you
read and edit). **Derived** rows cost an LLM call to remake, so they are stored. **Chunks, the
search indexes and links** are a cache.

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- e.g. embed_model, embed_dim

-- Bytes of every original and binary derived artifact, at files/<sha[0:2]>/<sha>.
CREATE TABLE blob (
    sha256      TEXT PRIMARY KEY,
    mime        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE page (
    id          TEXT PRIMARY KEY,              -- ULID
    slug        TEXT NOT NULL UNIQUE,          -- set at creation, never changed
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',      -- Markdown, may contain [[slug]] links
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Rev 1 is written at creation; every title or body change adds one. Tags are not revisioned.
CREATE TABLE page_rev (
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    rev         INTEGER NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    author      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (page_id, rev)
);

CREATE TABLE tag (
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,                 -- lower-case, '/' allowed
    PRIMARY KEY (page_id, tag)
);
CREATE INDEX tag_by_name ON tag(tag);

CREATE TABLE capture (
    id          TEXT PRIMARY KEY,              -- ULID minted by the client: the retry key
    kind        TEXT NOT NULL CHECK (kind IN ('photo', 'note', 'url', 'file')),
    text        TEXT,
    url         TEXT,
    source      TEXT NOT NULL,                 -- 'pwa', 'share', 'mcp'
    author      TEXT NOT NULL,
    created_at  TEXT NOT NULL,                 -- on the device
    received_at TEXT NOT NULL,                 -- on the server
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE
);
CREATE INDEX capture_by_page ON capture(page_id);

CREATE TABLE capture_blob (
    capture_id  TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    sha256      TEXT NOT NULL REFERENCES blob(sha256),
    filename    TEXT,
    PRIMARY KEY (capture_id, ord)
);

-- One current result per (capture, source blob, kind). Regenerating replaces it.
CREATE TABLE derived (
    id            INTEGER PRIMARY KEY,
    capture_id    TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    source_sha256 TEXT NOT NULL DEFAULT '',    -- '' when derived from the capture's text or url
    kind          TEXT NOT NULL CHECK (kind IN
                    ('ocr', 'fetched', 'description', 'summary', 'excalidraw')),
    producer      TEXT NOT NULL,               -- model id, tool name, or 'human'
    text          TEXT,                        -- indexed
    out_sha256    TEXT REFERENCES blob(sha256),  -- binary output, e.g. the .excalidraw file
    created_at    TEXT NOT NULL,
    UNIQUE (capture_id, source_sha256, kind)
);

CREATE TABLE job (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('extract', 'redraw', 'summarise', 'index')),
    capture_id   TEXT REFERENCES capture(id) ON DELETE CASCADE,
    page_id      TEXT REFERENCES page(id) ON DELETE CASCADE,
    state        TEXT NOT NULL DEFAULT 'queued'
                   CHECK (state IN ('queued', 'running', 'done', 'dead')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    run_after    TEXT NOT NULL,
    last_error   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX job_ready ON job(state, run_after);

-- ---- Index: rebuilt from page and derived by `scrap reindex`. ----

-- Chunks are never updated: the index job deletes a page's chunks and inserts new ones.
CREATE TABLE chunk (
    id          INTEGER PRIMARY KEY,
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    derived_id  INTEGER REFERENCES derived(id) ON DELETE CASCADE,  -- NULL: from the page body
    ord         INTEGER NOT NULL,
    text        TEXT NOT NULL
);
CREATE INDEX chunk_by_page ON chunk(page_id);

CREATE VIRTUAL TABLE chunk_fts USING fts5(
    text, content='chunk', content_rowid='id', tokenize='porter unicode61'
);

-- Needs sqlite-vec. The dimension is fixed by the model recorded in meta.
CREATE VIRTUAL TABLE chunk_vec USING vec0(
    chunk_id  INTEGER PRIMARY KEY,
    embedding float[384]
);

-- Keep chunk_fts and chunk_vec in step with chunk, including cascaded deletes.
CREATE TRIGGER chunk_ai AFTER INSERT ON chunk BEGIN
    INSERT INTO chunk_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER chunk_ad AFTER DELETE ON chunk BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES ('delete', old.id, old.text);
    DELETE FROM chunk_vec WHERE chunk_id = old.id;
END;
CREATE TRIGGER chunk_bu BEFORE UPDATE ON chunk BEGIN
    SELECT RAISE(ABORT, 'chunks are immutable: delete and insert');
END;

CREATE TABLE link (
    src_page_id TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    dst_slug    TEXT NOT NULL,                 -- may not exist yet
    PRIMARY KEY (src_page_id, dst_slug)
);
CREATE INDEX link_by_dst ON link(dst_slug);
```

Notes:

- **IDs** are ULIDs as text, safe to mint on the phone. Times are ISO 8601 UTC. Blobs are
  content-addressed, so a photo shared twice is stored once.
- **Derived** rows sit beside the untouched original. Regenerating overwrites the row: newest wins.
- **Chunks** are about 300 to 500 tokens, from the page body and the capture's derived text. The
  `index` job, in one transaction, deletes the page's chunks (the trigger clears FTS and vectors),
  inserts new chunks, and inserts each embedding into `chunk_vec` under the chunk's id.
- **Changing the embedding model** means dropping and recreating `chunk_vec` with the new
  dimension, updating `meta`, and re-embedding everything. `scrap reindex` does this when the
  configured model differs from `meta`. One model at a time; no mixing.
- **Indexed** is text only: titles, bodies, OCR and fetched text, and Claude's description of each
  image. Not pixels, and not raw Excalidraw JSON (coordinates and IDs). A whiteboard is found by
  what is written on it and what Claude says it shows.

### Page identity, links, tags

- **Identity.** The ULID. The slug (from the first title, suffixed on collision) never changes, so
  `[[slug]]` links survive renames at the cost of a slug that drifts from the title. A deleted
  page's slug may be reused and old links then point at the new page; accepted for one user.
- **Links.** `[[slug]]` or `[[slug|label]]` in Markdown, parsed into `link` on save. Dangling links
  are allowed; backlinks are a query on `link_by_dst`.
- **Tags.** Flat, lower-case strings, `/` allowed for loose grouping. Claude suggests them in
  `summarise`; the PWA adds and removes them.

## Phone quick capture

The installed PWA opens on the capture screen: camera, note, and a "recent" strip with state.

1. **Tap the icon.** The app shell loads from the service worker cache, even offline.
2. **Choose an input.**
   - *Camera*: `<input type="file" accept="image/*" capture="environment">`, or the gallery;
     several shots can go into one capture.
   - *Note*: a text box; the first line is the provisional title.
   - *Share*: the manifest's `share_target` takes URLs, text and files from the share sheet. It
     works for installed PWAs on Android, not iOS (where a Shortcut could post to the API).
3. **Save.** The client mints a ULID, stores the capture in IndexedDB and shows it as *queued*.
4. **Upload.** The app posts it to `POST /api/captures` and deletes the local copy on success. On
   failure it stays queued and retries with backoff while the app is open, and on next open.
5. **Store.** The server writes blobs to `files/`, then in one transaction inserts the blob,
   capture, page (rev 1) and first job rows, and returns `201`; a repeated ULID returns `200`. No
   LLM call on this path.
6. **Process.** The worker runs the jobs; the PWA polls `GET /api/captures?since=...` while open.

```text
Phone (PWA)                           scrap API              job worker            Claude / local
   |                                      |                       |                       |
   | save -> IndexedDB, show "queued"     |                       |                       |
   |-- POST /api/captures (ULID) -------->|                       |                       |
   |                                      | blobs, capture, page, |                       |
   |                                      | enqueue 'extract'     |                       |
   |<----------------- 201 ---------------|                       |                       |
   | delete local copy, show "saved"      |                       |                       |
   |                                      |      claim job ------>|                       |
   |                                      |                       |-- OCR + describe ---->|
   |                                      |                       |<-- text, kind --------|
   |                                      |                       |-- (whiteboard) redraw>|
   |                                      |                       |<-- .excalidraw -------|
   |                                      |                       |-- summarise --------->|
   |                                      |                       |<-- title, tags -------|
   |                                      |                       | chunk + embed (local) |
   |-- GET /api/captures?since ---------->|                       |                       |
   |<-- states, page link ----------------|                       |                       |
```

### Background jobs

Each job does one step and enqueues the next, so a failure retries only that step.

| Job | Does | Writes |
| --- | --- | --- |
| `extract` | Photo or file: one Claude vision call returns text, a short description and a kind (whiteboard, document, screenshot, photo). URL: fetch and extract readable text. Note: nothing. | `ocr`, `description`, `fetched` |
| `redraw` | Whiteboard only: Claude produces an Excalidraw scene from the photo, checked to parse as Excalidraw JSON before saving | `excalidraw` |
| `summarise` | Claude writes a summary, a better title and tags. It replaces the provisional title only if the page has not been edited since rev 1. | `summary`, page rev, tags |
| `index` | Re-chunk the page and its derived text, embed locally, re-parse links | `chunk`, `chunk_fts`, `chunk_vec`, `link` |

`redraw` runs beside the main chain: `summarise` and `index` do not wait for it, and its failure
leaves the page intact. Page edits from the PWA or MCP also enqueue `index`.

**States.** `queued` -> `running` -> `done`. On error the job goes back to `queued` with
`run_after = now + 2^attempts minutes`; after five attempts it is `dead`. A job left `running` by a
crash is requeued at start-up. The worker claims with
`UPDATE job SET state = 'running' ... WHERE id = (SELECT ...) RETURNING`.

**Failure visibility.** The recent strip shows each capture as queued, saved, processing, done or
failed (a dead job), with `last_error` and a *retry* button. The original and the page already
exist, so nothing is lost.

## Excalidraw

The whiteboard photo is the source of truth; the drawing is derived and can be regenerated at any
time. Both are shown side by side on the page. The PWA embeds the Excalidraw React component to view
and edit the drawing. Saving an edit overwrites the `excalidraw` row with producer `human`, and
regenerating asks before replacing a human edit.

## MCP tools (v0)

Served at `/mcp`. Results carry each page's PWA URL (`https://<serve-host>/p/<slug>`) and say when
it has images, so Claude links there instead of trying to show them.

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search` | `query`, optional `tags`, `limit` | Ranked pages: title, URL, best snippets and where each came from |
| `read` | `slug` | Title, tags, body, backlinks, attachments with their descriptions, OCR text and URLs |
| `recent` | optional `days`, `limit` | Recently created or updated pages |
| `write` | new page (`title`, `body`), or `slug` with `body` to replace or `append`; optional `tags` | Page URL and revision |
| `ingest` | `url` or `text` | A capture id; it runs the same jobs as a phone capture |

`write` records the caller as the revision author. Deletion is a PWA action only.

## Security posture

- **Tailnet only.** Serve is the only way in and Funnel stays off. The tailnet policy grants the
  scrap device to the owner's own devices only; tagged servers (for example any internet-facing
  box) must not be able to reach it. The service listens on loopback, so only Serve can set the
  identity headers.
- **Identity is attribution, not the gate.** The ACL is the gate. `author` is the
  `Tailscale-User-Login` header. Tagged devices send none, so their requests are recorded with the
  fallback author `tagged`.
- **What it holds.** Its database, files and Claude credential. No cluster credentials
  (service-account token automount off), no git credentials, no shell tools.
- **Prompt injection.** Ingested content is untrusted data. Ingest calls Claude with a fixed prompt
  and no tools and checks the output against a schema; the worst outcome is a wrong page, which
  `page_rev` can undo. URL fetching refuses private and tailnet addresses, re-checked after DNS
  resolution and after every redirect.
- **Reading is not acting.** Sessions that read scrap may meet injected text. Sessions holding
  cluster or other powerful credentials should not mount the scrap MCP server.

## Deferred to v0.1

- Voice memos (needs a transcriber).
- Background Sync for the upload queue.
- Filing captures into existing pages, and automatic cross-linking.
- Markdown export (one `<slug>.md` per page, attachments beside it; never read back as the store).
- A `namespace` column for read scoping by less trusted surfaces.
- Keeping old derived rows on regeneration, with pruning.
- A status page for dead jobs.
- `scrap gc` to sweep orphan blobs.

## Deferred, larger

Each is independent and none is needed for v0.

- **Work browser route.** A Cloudflare tunnel plus Access (passkey-capable IdP, short sessions) in
  front of the PWA only; the service verifies the Access JWT itself. Cloudflare sees plaintext.
- **Work sandbox.** Userspace Tailscale (no root, no TUN), an ephemeral tagged key, an ACL to the
  MCP port only; scoped `search` and `read`, inbox-only writes.
- **PKM session pod.** A remote Claude Code session in the cluster with only the scrap MCP server.
- **Separate ingest worker.** The same image with another command, if LLM work needs isolating.

## Open questions

- **How ingest calls Claude.** Messages API with structured output (simplest to sandbox) or the
  Claude Code CLI on a subscription login (no API billing, but a login to keep alive). With one
  capture per page there is no tool loop, so the Agent SDK is not needed.
- **Audio transcription.** Local faster-whisper (CPU cost) or a hosted API (another integration).
- **Embedding model.** bge-small or nomic-embed-text, decided on a test set of real captures.
- **Postgres and pgvector**, only if SQLite is outgrown. Not expected for one person.
- **Cloudflare route auth.** Which identity provider and session length; capture or view only.
- **Work sandbox scope.** Namespaced reads or full read; whether work material gets a namespace.
- **Tailscale Kubernetes operator.** Whether its ingress passes the identity headers through, or a
  `tailscale serve` sidecar is needed (assumed above).
