# scrap design

Status: design stage. This records what v0 is, why, and what is left open. It replaces an earlier,
much larger system whose ideas (classified, cross-linked pages; semantic recall with cited sources;
MCP tools for Claude) are kept, and whose machinery (a git-synced Markdown vault, a chat-bot daemon,
a stack of paid APIs each with its own integration layer) is not.

## Principles

1. **Tiny.** One process, one database file, one folder of files. If a feature needs a second
   service, it waits.
2. **Off the shelf.** Claude is the chat interface and does the reading and writing that needs
   judgement. SQLite does storage and search. Tailscale does networking and identity. Excalidraw
   does drawings. scrap is the glue.
3. **Originals are sacred, everything else is derived.** A photo, voice memo, file or note is
   stored as received and never changed. OCR text, summaries, descriptions and drawings are
   derived from it, labelled with what produced them, and can be regenerated.
4. **The index is disposable.** Chunks, full-text and vector indexes, and the link table are
   rebuilt from pages and derived text with one command. Losing them loses nothing.
5. **Capture never waits.** Saving a capture is a file write and a row insert. Anything slow runs
   later in a background job.
6. **Claude reasons, the PWA shows.** Claude (over MCP) is for asking and writing; the PWA is for
   capturing and looking. Answers link into the PWA.

## v0 scope

```text
 phone / laptop browser            Claude Code (tailnet host)
          |  HTTPS                         |  MCP over HTTPS
          v                                v
   +-------------------- Tailscale Serve --------------------+
   |  terminates TLS, adds Tailscale-User-* identity headers |
   +---------------------------+-----------------------------+
                               | http://127.0.0.1
                               v
   +-------------------- scrap (one process) ----------------+
   |  FastAPI: PWA static files, JSON API, MCP endpoint      |
   |  job worker (in-process thread): OCR, summary, redraw,  |
   |    transcription, chunk + embed (fastembed, local)      |
   +-------------+-------------------------+-----------------+
                 v                         v
        scrap.db (SQLite:            files/ (content-addressed
        FTS5 + sqlite-vec)            originals and derived blobs)
```

- **One Python service.** FastAPI serves the built PWA, a small JSON API for it, and an MCP server
  (streamable HTTP) mounted on the same app. A single worker thread drains the job queue.
- **Storage.** SQLite in WAL mode, and a `files/` folder keyed by SHA-256. Both live on one
  persistent volume. Backup is a SQLite online backup plus a copy of `files/`.
- **Search.** Hybrid: an FTS5 (BM25) query and a sqlite-vec nearest-neighbour query each return a
  ranked list of chunks; reciprocal rank fusion (`score = sum(1 / (60 + rank))`) merges them, then
  hits are grouped by page. No reranker in v0.
- **Embeddings.** Local, through fastembed (ONNX, CPU, runs on arm64 and amd64). Default
  `BAAI/bge-small-en-v1.5` (384 dimensions); `nomic-embed-text` (768) is the alternative if recall
  is poor. The model name is stored per chunk, so switching models is a re-embed, not a migration.
- **LLM work.** Claude does OCR, descriptions, summaries, classification and Excalidraw redraws.
  How it is invoked is an open question (see below).
- **Access.** Tailscale Serve is the only way in. The service binds to `127.0.0.1` in its pod, so
  only Serve (in a sidecar) can reach it, and it trusts the `Tailscale-User-Login` header for
  attribution. There is no login code.
- **Deployment.** One multi-arch container image (arm64 and amd64) on a home k3s cluster with
  mixed ARM and x86 nodes, with a persistent volume and a Tailscale sidecar.

## Data model

The source of truth is three things: **captures** (what arrived), **blobs** (the bytes of
originals), and **pages** (the curated notes that people and Claude edit). **Derived artifacts**
are regenerable at a cost (an LLM call), so they are stored and versioned. **Chunks, the search
indexes and links** are cheap to rebuild and are treated as a cache.

```text
capture --has--> capture_blob --> blob (original)
   |                                |
   | filed into                     | source of
   v                                v
  page <--- derived artifacts (ocr, transcript, description, summary, excalidraw)
   |               |
   +---- chunk <---+   (index: chunk_fts, chunk_vec, link -- all rebuildable)
```

### Schema sketch

Validated by running it with Python's `sqlite3` (SQLite 3.50) into an in-memory database, with the
sqlite-vec extension loaded for the last table. IDs are ULIDs as text: sortable by time, safe to
mint on the phone, and stable across export and import. Times are ISO 8601 UTC text.

```sql
PRAGMA foreign_keys = ON;

-- Bytes of every original and every binary derived artifact, stored at files/<sha[0:2]>/<sha>.
CREATE TABLE blob (
    sha256      TEXT PRIMARY KEY,
    mime        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);

-- A curated note. Identity is the ULID; the slug is for URLs, links and export.
CREATE TABLE page (
    id          TEXT PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,          -- set once at creation, never changed
    title       TEXT NOT NULL,                 -- free to change
    body        TEXT NOT NULL DEFAULT '',      -- Markdown, may contain [[slug]] links
    kind        TEXT NOT NULL DEFAULT 'note',  -- note, whiteboard, article, meeting, ...
    namespace   TEXT NOT NULL DEFAULT 'main',  -- read-scope boundary for later surfaces
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Every edit to a page body, so a bad write (human, Claude or injected) can be undone.
CREATE TABLE page_rev (
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    rev         INTEGER NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    author      TEXT NOT NULL,                 -- tailnet login, 'claude:<job>' or 'mcp:<login>'
    created_at  TEXT NOT NULL,
    PRIMARY KEY (page_id, rev)
);

CREATE TABLE tag (
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,                 -- lower-case, e.g. 'epics' or 'home/garden'
    PRIMARY KEY (page_id, tag)
);
CREATE INDEX tag_by_name ON tag(tag);

-- One thing that arrived: one tap of "save" in the PWA, one MCP ingest call.
CREATE TABLE capture (
    id          TEXT PRIMARY KEY,              -- ULID minted by the client
    kind        TEXT NOT NULL CHECK (kind IN ('photo', 'note', 'voice', 'url', 'file')),
    text        TEXT,                          -- typed note or caption
    url         TEXT,                          -- shared link
    source      TEXT NOT NULL,                 -- 'pwa', 'share', 'mcp'
    author      TEXT NOT NULL,
    created_at  TEXT NOT NULL,                 -- when captured on the device
    received_at TEXT NOT NULL,                 -- when the server stored it
    page_id     TEXT REFERENCES page(id) ON DELETE SET NULL  -- set once filed
);
CREATE INDEX capture_by_page ON capture(page_id);

CREATE TABLE capture_blob (
    capture_id  TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    sha256      TEXT NOT NULL REFERENCES blob(sha256),
    filename    TEXT,
    PRIMARY KEY (capture_id, ord)
);

-- Something a producer made from a capture's blob or text. Never edited; superseded instead.
CREATE TABLE derived (
    id            INTEGER PRIMARY KEY,
    capture_id    TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    source_sha256 TEXT REFERENCES blob(sha256),          -- NULL when derived from text or url
    kind          TEXT NOT NULL CHECK (kind IN
                    ('ocr', 'transcript', 'fetched', 'description', 'summary', 'excalidraw')),
    producer      TEXT NOT NULL,          -- e.g. 'claude-vision', 'whisper', 'readability'
    producer_ver  TEXT NOT NULL,          -- model id or package version
    prompt_ver    TEXT,                   -- version of the prompt used, if any
    text          TEXT,                   -- text output (indexed)
    out_sha256    TEXT REFERENCES blob(sha256),          -- binary output, e.g. .excalidraw
    created_at    TEXT NOT NULL,
    superseded_at TEXT                    -- set when a newer run replaces this one
);
CREATE UNIQUE INDEX derived_current
    ON derived(capture_id, coalesce(source_sha256, ''), kind) WHERE superseded_at IS NULL;

-- Background work. A single in-process worker claims rows with UPDATE ... RETURNING.
CREATE TABLE job (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,           -- 'extract', 'describe', 'redraw', 'file', 'index'
    capture_id   TEXT REFERENCES capture(id) ON DELETE CASCADE,
    page_id      TEXT REFERENCES page(id) ON DELETE CASCADE,
    state        TEXT NOT NULL DEFAULT 'queued'
                   CHECK (state IN ('queued', 'running', 'done', 'failed', 'dead')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    run_after    TEXT NOT NULL,           -- backoff: now + 2^attempts minutes
    last_error   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX job_ready ON job(state, run_after);

-- ---- Index: everything below is rebuilt from page and derived by `scrap reindex`. ----

CREATE TABLE chunk (
    id          INTEGER PRIMARY KEY,
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    derived_id  INTEGER REFERENCES derived(id) ON DELETE CASCADE,  -- NULL: from the page body
    ord         INTEGER NOT NULL,
    text        TEXT NOT NULL,
    embed_model TEXT NOT NULL
);
CREATE INDEX chunk_by_page ON chunk(page_id);

CREATE VIRTUAL TABLE chunk_fts USING fts5(
    text, content='chunk', content_rowid='id', tokenize='porter unicode61'
);

CREATE TABLE link (
    src_page_id TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    dst_slug    TEXT NOT NULL,            -- may not exist yet: a dangling link is allowed
    PRIMARY KEY (src_page_id, dst_slug)
);
CREATE INDEX link_by_dst ON link(dst_slug);

-- Needs the sqlite-vec extension loaded. Dimension follows the embedding model (384 for bge-small).
CREATE VIRTUAL TABLE chunk_vec USING vec0(
    chunk_id  INTEGER PRIMARY KEY,
    embedding float[384]
);
```

### What each part is for

- **blob**: content-addressed bytes, so a photo shared twice is stored once and a file's identity
  is its hash. The folder layout is the only file layout; there is no human-facing tree.
- **capture**: the receipt for what arrived, with the client-minted ULID as an idempotency key. A
  retried upload with the same ID is a no-op. Captures are kept after filing, so a page can always
  show "made from these photos, this memo".
- **page**: what you read, search and link to. A page collects one or more captures (a meeting
  page might hold three whiteboard photos and a voice memo) plus text written by Claude or by
  hand. `page_rev` keeps every body edit.
- **derived**: one row per producer run. The original is always kept beside it. A newer model or
  prompt writes a new row and sets `superseded_at` on the old one; the partial unique index keeps
  exactly one current row per (capture, source, kind). Old rows stay for comparison until pruned.
- **job**: the queue. See the capture flow below.
- **chunk, chunk_fts, chunk_vec, link**: the index. Chunks come from page bodies and from the
  current `ocr`, `transcript`, `fetched`, `description` and `summary` text, about 300 to 500 tokens
  each with a small overlap, each tagged with its page so hits group by page.

### What is indexed

Text only: page titles and bodies, OCR and transcript text, fetched article text, and the
Claude-written description of each image or drawing. Pixels are not embedded, and raw Excalidraw
JSON is not indexed (it is coordinates and IDs, noise to both BM25 and embeddings). A whiteboard is
found by what is written on it and what Claude says it shows.

### Page identity, links, tags

- **Identity.** The ULID is the identity; everything references it. The slug (from the first
  title, e.g. `ring-lattice-sketch`, with a suffix on collision) is fixed at creation and never
  changes, even when the title does. That makes `[[slug]]` links and exported filenames permanent
  without rename tracking or rewriting other pages' bodies. A slightly stale slug is a fair price.
- **Links.** Written in Markdown bodies as `[[slug]]` or `[[slug|label]]`, which is easy for both
  Claude and a person to type. The `link` table is parsed from bodies on save and on reindex.
  Links may point at a slug that does not exist yet, which is how Claude can propose a page.
  Backlinks are a query on `link_by_dst`.
- **Tags.** Flat, lower-case strings, with `/` allowed for loose grouping. Claude suggests them
  when filing; the PWA can add and remove them. No tag hierarchy or tag pages. `namespace` is a
  separate, coarse boundary (for example `main` and `work`) reserved for read scoping by later,
  less trusted surfaces; v0 has one namespace.

### Markdown export

`scrap export <dir>` writes one `<slug>.md` per page with YAML front matter (id, title, tags,
kind, created, updated, captures), the body as is, and attachments copied beside it with links
rewritten to relative paths. The current `.excalidraw` drawing is written as a plain
`.excalidraw` file next to its photo. Export is one-way, for reading, backup and leaving; scrap
never reads it back as its store. An import command can come later if it is ever needed.

## Phone quick capture

The PWA is installed to the phone's home screen. It opens straight onto the capture screen:
camera, note, voice, and a "recent" strip below showing the last captures and their processing
state.

1. **Tap the icon.** The app shell loads from the service worker cache, so it opens offline and
   instantly.
2. **Choose an input.**
   - *Camera*: `<input type="file" accept="image/*" capture="environment">` opens the camera;
     several shots can go into one capture. Choosing from the gallery uses the same input without
     `capture`.
   - *Note*: a text box; the first line becomes the provisional title.
   - *Voice*: `MediaRecorder` records Opus in WebM or MP4 (whatever the phone supports).
   - *Share target*: the manifest's `share_target` accepts URLs, text and files from the phone's
     share sheet and lands on a confirmation screen with an optional caption.
3. **Save.** The client mints a ULID, writes the capture (metadata and blobs) to IndexedDB, and
   shows it in the recent strip as *queued*. The UI is done; you can put the phone away.
4. **Upload.** The service worker posts the capture as multipart to `POST /api/captures` with the
   ULID. On success it deletes the local copy. On failure or offline it keeps it and retries on
   the next app open, on `online` events and, where supported, Background Sync, with backoff.
5. **Store.** The server hashes and writes each blob to `files/`, inserts `capture`, `blob` and
   `capture_blob` rows and the first job in one transaction, and returns `201` with the ID. A
   repeated ULID returns `200` with the existing capture. No LLM call happens on this path.
6. **Process.** The worker runs the jobs for the capture (below). The PWA polls
   `GET /api/captures?since=...` while it is open and updates each item's state.

```text
Phone (PWA + service worker)          scrap API              job worker            Claude / local
   |                                      |                       |                       |
   | save -> IndexedDB, show "queued"     |                       |                       |
   |-- POST /api/captures (ULID) -------->|                       |                       |
   |                                      | write blobs, rows,    |                       |
   |                                      | enqueue 'extract'     |                       |
   |<----------------- 201 ---------------|                       |                       |
   | delete local copy, show "saved"      |                       |                       |
   |                                      |      claim job ------>|                       |
   |                                      |                       |-- OCR + describe ---->|
   |                                      |                       |<-- text, kind --------|
   |                                      |                       |-- (whiteboard) redraw>|
   |                                      |                       |<-- .excalidraw -------|
   |                                      |                       |-- summarise, file --->|
   |                                      |                       |<-- page plan ---------|
   |                                      |                       | chunk + embed (local) |
   |-- GET /api/captures?since ---------->|                       |                       |
   |<-- states, page link ----------------|                       |                       |
```

### Background jobs

Each job does one step, writes its result and enqueues the next, so a failure is retried at the
step that failed and earlier work is not redone.

| Job | Input | Does | Output |
| --- | --- | --- | --- |
| `extract` | capture | Photo or file: Claude vision returns text, a short description and a kind (whiteboard, document, screenshot, photo). Voice: transcription. URL: fetch and extract readable text. Note: nothing. | `derived` rows: `ocr`, `description`, `transcript`, `fetched` |
| `redraw` | whiteboard image | Claude produces an Excalidraw scene from the photo, validated as Excalidraw JSON before saving | `derived` `excalidraw` with `out_sha256` |
| `file` | capture and its derived text | Claude writes a summary and decides: new page or append to an existing one (it is shown the top search hits), title, tags, links | `derived` `summary`; page created or updated; `capture.page_id` set |
| `index` | page | Re-chunk the page and its current derived text, embed locally, update FTS and vectors, re-parse links | `chunk`, `chunk_fts`, `chunk_vec`, `link` |

`redraw` runs only when `extract` says the image is a whiteboard or diagram, and is not on the
critical path: `file` and `index` do not wait for it, and its failure does not affect the page.

**States and retries.** `queued` -> `running` -> `done`, or back to `queued` with
`run_after = now + 2^attempts minutes` on error, until `max_attempts`, then `dead`. A job left
`running` by a crash is reset to `queued` at start-up. Errors are stored in `last_error`.

**Failure visibility.** The recent strip shows each capture as queued, uploading, saved,
processing, filed (with a link to its page) or failed. A failed capture shows the error and a
*retry* button that requeues its dead job. A small status page lists dead jobs. Nothing is ever
lost by a failure: the original and the capture row are already stored, and an unfiled capture is
still found by its date in the PWA.

## Excalidraw

The whiteboard photo is the source of truth; the drawing is a derived artifact, regenerable from
the photo with a better model or prompt at any time. Both are kept and shown side by side on the
page.

The PWA embeds the Excalidraw React component to view the current drawing and to edit it. An edit
is saved as a new `derived` row with producer `human` (superseding the generated one), so a hand
correction is not silently overwritten: regenerating asks first when the current drawing is a
human edit. The indexed text for a whiteboard is its OCR text and description, not the scene JSON.
Drawings can also start from scratch in the PWA, as a capture of kind `file` with an `.excalidraw`
blob.

## MCP tools (v0)

Served at `/mcp` on the same app, over streamable HTTP. Every result that refers to a page carries
its PWA URL (`https://<serve-host>/p/<slug>`), and image-bearing results say so, so Claude can tell
the user to open the link rather than trying to show the image.

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search` | `query`, optional `tags`, `kind`, `limit` | Ranked pages with title, slug, URL, best matching snippets and which derived artifact each came from |
| `read` | `slug` or `id` | Title, tags, body, backlinks, and a list of attachments (originals and derived) with their descriptions, OCR text and PWA URLs |
| `recent` | optional `days`, `limit` | Recently created or updated pages and unfiled captures |
| `write` | `title` and `body` for a new page, or `slug` plus `body` to replace or `append` to add; optional `tags` | The page URL and new revision number |
| `ingest` | `url` or `text`, optional `note` | A capture ID; it goes through the same jobs as a phone capture |

`write` records the MCP caller as the revision author. There is no delete over MCP in v0; deletion
is a PWA action.

## Security posture

- **Tailnet only in v0.** Tailscale Serve is the single entry point; the tailnet ACL decides which
  devices reach it. The service listens on loopback, so the identity headers that Serve sets cannot
  be forged by anything else. Requests from tagged devices arrive without user identity headers;
  v0 treats reachability (the ACL) as the gate and the headers as attribution only.
- **What the service holds.** Its own database and files, and the credential for whatever it uses
  to call Claude. No cluster credentials, no Kubernetes service-account token (automount off), no
  git credentials, no shell tools.
- **Prompt injection.** Everything ingested (web pages, PDFs, OCR of photos of other people's
  slides) is untrusted data. The ingest path calls Claude with a fixed prompt and no tools, or a
  fixed allow-list of scrap's own tools, and parses its output against a schema. It cannot run
  commands, cannot reach the cluster API, and its worst outcome is a wrong or misleading page,
  which `page_rev` can undo. URL fetching refuses private and tailnet addresses (SSRF guard).
- **Reading is not acting.** Claude sessions that read scrap through MCP may meet injected text
  inside pages. The sessions that hold cluster or other powerful credentials should not mount the
  scrap MCP server; the one that deploys scrap does not need to read it.

## Deferred

Each of these is independent and none is needed for v0.

- **Work browser route.** A Cloudflare tunnel plus Access (passkey-capable identity provider,
  short sessions) in front of the PWA only, not MCP. The service verifies the Access JWT itself
  (`Cf-Access-Jwt-Assertion`, audience and signature against the team's keys) rather than trusting
  the tunnel. Cloudflare sees plaintext on this path.
- **Work sandbox access.** A Claude Code sandbox at work joins the tailnet with userspace Tailscale
  (no root, no TUN) and an ephemeral, tagged auth key; the ACL allows only the MCP port. It gets a
  reduced tool set: `search` and `read` limited to permitted namespaces, and writes only to an
  inbox namespace for review.
- **Locked-down PKM session pod.** A remote Claude Code session in the cluster with only the scrap
  MCP server configured and no cluster credentials, for a chat-only way in from any device.
- **Separate ingest worker.** Move the job worker into its own pod (same image, different
  command) if LLM work ever needs isolating from the API, or needs more memory than the API
  should hold.

## Open questions

- **How Claude is invoked for ingest.** Plain Messages API calls with an API key (simplest and
  easiest to sandbox), the Agent SDK (tool loops for `file`, which needs to search before
  deciding), or the Claude Code CLI on a subscription login (no API billing, but a login to keep
  alive inside a pod). Leaning towards direct API calls with structured output, with the `file`
  step given scrap's own `search` as its one tool.
- **Audio transcription engine.** Local faster-whisper (CPU cost on small nodes, model size vs
  accuracy) or a hosted speech-to-text API (one more paid integration).
- **Embedding model.** bge-small is fast and small; nomic-embed-text handles longer chunks.
  Decide on a test set of real captures.
- **Postgres and pgvector** only if SQLite is outgrown (concurrent writers, size). Not expected for
  one person.
- **Auth for the Cloudflare route.** Which identity provider and session length, and whether the
  work route may capture or only view.
- **Work sandbox read scope.** Namespaced reads only, or full read; and whether work material gets
  its own namespace at all.
- **Identity behind the Tailscale Kubernetes operator.** Whether its ingress passes the
  `Tailscale-User-*` headers through, or a `tailscale serve` sidecar is needed (assumed above).
- **Page filing quality.** How much context the `file` step gets (top N search hits, tag list)
  before it decides between a new page and an append, and whether ambiguous cases go to an inbox.
