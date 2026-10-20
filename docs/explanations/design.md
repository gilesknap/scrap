# scrap design

Status: design stage. It keeps the ideas of an earlier, much larger system (classified pages,
semantic recall, MCP tools) and drops its machinery (a git-synced vault, a chat-bot daemon, a
stack of paid-API integrations).

## Principles

1. **Tiny.** One process, one database file, one folder of files. If a feature needs a second
   service, it waits.
2. **Off the shelf.** Claude does the reading and writing that needs judgement. SQLite does storage
   and search. Tailscale does networking and identity. Excalidraw does drawings. scrap is the glue.
3. **Originals are kept, everything else is derived** and can be regenerated, except a consume
   page's article once its source is gone. The search index is disposable and rebuilt with one
   command. Deleting a page deliberately deletes its capture too.
4. **Capture never waits.** Saving is a file write and a few row inserts; anything slow runs later
   in a background job.
5. **Claude reasons, the PWA shows.** Claude (over MCP) is for asking and writing; the PWA is for
   capturing and looking. Answers link into the PWA.

## v0 scope

- **One Python process.** FastAPI serves the built PWA, its JSON API and an MCP server (streamable
  HTTP). One worker thread runs the jobs: extract, redraw, summarise, index.
- **Storage.** SQLite in WAL mode and a `files/` folder keyed by SHA-256, on one persistent volume.
  Backup is a SQLite online backup plus a copy of `files/`. The API and the worker both write, so
  every connection runs `PRAGMA foreign_keys = ON` and `PRAGMA busy_timeout = 5000` on open,
  outside any transaction: the index stays correct only because deletes cascade.
- **Search.** An FTS5 (BM25) query and a sqlite-vec nearest-neighbour query each return ranked
  chunks; reciprocal rank fusion (`sum(1 / (60 + rank))`) merges them and hits are grouped by page.
- **Calling Claude.** One small function takes a prompt and optional files and returns JSON. It runs
  `claude -p` (headless Claude Code on a subscription login); the Messages API is a second backend
  chosen by an environment variable. There is no agent loop beyond reading one image.
- **Embeddings.** Local, through fastembed (ONNX on CPU, arm64 and amd64). Default
  `BAAI/bge-small-en-v1.5` (384 dimensions); `nomic-embed-text` (768) if recall is poor.
- **Access.** Tailscale Serve is the only way in; Funnel stays off. The service binds to
  `127.0.0.1` in its pod, so only Serve (in a sidecar) reaches it. No login code.
- **Deployment.** A multi-arch image on a home k3s cluster (ARM and x86 nodes), with a persistent
  volume and a Tailscale sidecar.

**One capture is one page.** Each capture creates its own page at once. A note's text becomes the
body and its first line the title; a URL capture's body is the link and its title the URL; a photo
or file page starts with an empty body (for your own words) and its date as title. Background jobs
then add derived text, a better title and slug, a summary and tags. Merging and cross-linking pages
come later, by hand or through MCP `write`. Ingest stays a fixed pipeline with no search-then-decide
loop.

## Data model

The source of truth is **captures** (what arrived), **blobs** (the bytes) and **pages** (what you
read and edit). **Derived** rows cost an LLM call to remake, so they are stored. **Chunks, the
search indexes and links** are a cache.

```sql
PRAGMA foreign_keys = ON;  -- per connection: the app sets it on every open

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
    slug        TEXT NOT NULL UNIQUE,          -- fixed once summarise has run
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',      -- Markdown, may contain [[slug]] links
    kind        TEXT NOT NULL DEFAULT 'note' CHECK (kind IN ('note', 'todo', 'consume',
                  'memory', 'reference', 'whiteboard', 'document')),
    kind_fixed  INTEGER NOT NULL DEFAULT 0 CHECK (kind_fixed IN (0, 1)),  -- 1: the user chose it
    fields      TEXT NOT NULL DEFAULT '{}' CHECK (json_type(fields) = 'object'),  -- flat
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX page_by_kind ON page(kind);

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
    updated_at   TEXT NOT NULL,
    CHECK (capture_id IS NOT NULL OR page_id IS NOT NULL)
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
- **Derived** rows sit beside the untouched original. Regenerating is an upsert
  (`ON CONFLICT DO UPDATE`, keeping the row id) and enqueues `index`: newest wins. Never
  `INSERT OR REPLACE` into `derived` or `chunk`: REPLACE deletes without firing `chunk_ad`.
- **Chunks** are about 300 to 500 tokens. The `index` job chunks and embeds first, holding no
  lock, then in one short `BEGIN IMMEDIATE` transaction replaces the page's chunks (the trigger
  clears FTS and vectors) and inserts each embedding under its chunk's id.
- **Changing the embedding model** means re-embedding everything. `scrap reindex` embeds every
  chunk first, then in one short write transaction drops and recreates `chunk_vec` with the new
  dimension (before deleting any chunk, since `chunk_ad` needs the table), updates `meta`, and
  replaces all chunks. One model at a time; no mixing. A page edited during `reindex` may
  briefly be found by its older text.
- **Indexed** is text only: the title, tags, summary field and body (a page's own chunk has a
  column for each, so ranking can weigh them: #84) and every derived text: OCR, fetched article,
  Claude's image description and the summary. Not pixels, and not raw Excalidraw JSON
  (coordinates and IDs). Pages with every word in the title rank first, then those with every
  word in the title, tags or summary, then by bm25 (column weights 10, 5, 3, 1).

### Page identity, links, tags

- **Identity.** The ULID. The slug is made from the title, suffixed on collision. `summarise`
  replaces the provisional title if it is unchanged since rev 1, and the slug too if, in addition,
  nothing links to the page. After that the slug never changes, so `[[slug]]` links survive
  renames, at the cost of a slug that drifts from the title. A deleted page's slug may be reused
  and old links then point at the new page; accepted for one user.
- **Links.** `[[slug]]` or `[[slug|label]]` in Markdown, parsed into `link` on save. Dangling links
  are allowed; backlinks are a query on `link_by_dst`.
- **Tags.** Flat, lower-case, `/` allowed. The PWA edits them; `summarise` adds them only on its
  first success and only to a page with none.

### Kinds

A page's `kind` is `note` (default and fallback), `todo`, `consume` (to read, watch or listen to),
`memory`, `reference`, `whiteboard` or `document`. scrap classifies and summarises; it never
rewrites the user's words or fits them to templates.

- **`fields`** is a flat JSON object (no nulls, no nested values in v0), not per-kind tables: a
  todo has `status` and optional `due`; consume has `subtype` (`read`, `watch`, `listen`),
  `status` and the `source` link.
- **Status** is one lifecycle for todo and consume, Thoth's: `open`, `in_progress`, `done`,
  `cancelled`. New pages start `open`; ticking a todo toggles `open` and `done`, and the other two
  are stored and shown (set by an import, richer controls later).
- **Choosing a kind.** The capture buttons (camera, gallery, note) only choose the input; the
  kind is chosen in the PWA's editor, for a new capture or an existing page, from Note
  (default), Todo, Read (`consume`), Whiteboard and Document (`memory` and `reference` are not
  offered until wanted; a hard-coded list until real use asks for configurable kinds). A bare
  URL pre-selects Read; photos skip the choice (ingest classifies them; the user can change it).
  The capture's `kind` field or `PATCH /api/pages/{id}` sets it.
- **A kind the user changes** (PWA edit, `PATCH`) **keeps every field** the page has (a summary,
  a due date, an imported status: a stray tap on a chip must lose nothing) and adds the new
  kind's defaults for the keys it lacks. So todo -> note -> todo comes back as it was, and a
  status or subtype carried over keeps its value.
- **A kind set by a capture, `extract` or `summarise`** starts from the new kind's
  defaults plus any checked model output: todo `{"status":"open"}`; consume
  `{"subtype":"read","status":"open"}` and `source`, always the capture's own URL (omitted if it has
  none). Either way the page is listed at once, even if `summarise` never succeeds.
- **The user wins**, as with titles. A kind chosen at capture or in the editor sets
  `kind_fixed`. `extract` and
  `summarise` set the kind only while it is still `note` and not fixed. `summarise` writes kind,
  `fields` and tags only on its first success; a regenerated summary replaces just the summary text,
  so a cleared `due` stays cleared. It calls Claude holding no lock, then in one `BEGIN IMMEDIATE`
  re-reads the page, picks the resulting `:kind`, checks the output against its schema (dropping
  other keys, nulls and `source`) and writes:

  ```sql
  UPDATE page SET kind = :kind, fields = CASE WHEN kind = :kind  -- json_patch: the 2nd wins
      THEN json_patch(:fields, fields)     -- chosen kind: existing keys win
      ELSE json_patch(:defaults, :fields)  -- new kind: its defaults plus the checked output
    END
  WHERE id = :id AND NOT EXISTS (          -- first success only: no summary yet
      SELECT 1 FROM capture c JOIN derived d ON d.capture_id = c.id
      WHERE c.page_id = :id AND d.kind = 'summary');
  ```

- **Consume keeps link and summary only.** The same transaction runs this `UPDATE` and the tag
  insert first, then writes the summary row, then deletes the `fetched` text if the stored kind is
  now `consume`. Only regenerating the summary re-fetches it, for example after a change to
  `reference`.
- **Views.** One list screen (Search; `/recent` redirects to it): an empty box lists every page
  newest first, a fixed kind row (All, Notes, Todos, Reads, Boards, Docs) sets or clears `kind:`,
  and the query rides in the address (`/search?q=...`). A todo's page has a Done/Reopen tick
  setting `fields.status`. No Inbox: `kind_fixed` is only for the user-wins rule.

## Phone quick capture

1. **Tap the icon.** The installed PWA opens from the service worker cache, even offline, on the
   capture screen: camera, gallery and note buttons (how to capture; the kind is chosen in the
   composer), and a "recent" strip with each capture's state.
2. **Choose an input.**
   - *Camera*: `<input type="file" accept="image/*" capture="environment">`, or the gallery;
     several shots can go into one capture.
   - *Note*: a text box.
   - *Share*: the manifest's `share_target` takes URLs, text and files from the share sheet. It
     works for installed PWAs on Android, not iOS (where a Shortcut could post to the API).
     Android often sends a link as `text`, so the server lifts a bare URL in `text` into `url`.
3. **Save.** The client mints a ULID, stores the capture in IndexedDB and shows it as *queued*.
4. **Upload.** The app posts it to `POST /api/captures` and deletes the local copy on success. On
   failure it stays queued and retries with backoff while the app is open, and on next open.
5. **Store.** The server writes blobs to `files/`, then in one `BEGIN IMMEDIATE` transaction looks
   up the capture id (found: a retry, return `200`), else inserts blobs (`ON CONFLICT DO NOTHING`),
   page (before capture, for the foreign key; a chosen kind sets `kind`, `kind_fixed` and
   default `fields`), `page_rev` 1, capture, `capture_blob`, and the `extract` and `index` jobs, and returns
   `201`. No LLM call on this path, and the note or title is searchable even if Claude is down.
6. **Process.** The worker runs the jobs; the PWA polls `GET /api/captures?since=...` while open.

```text
Phone (PWA)                           scrap API              job worker            Claude / local
   |                                      |                       |                       |
   | save -> IndexedDB, show "queued"     |                       |                       |
   |-- POST /api/captures (ULID) -------->|                       |                       |
   |                                      | page, rev 1, capture, |                       |
   |                                      | enqueue extract, index|                       |
   |<----------------- 201 ---------------|                       |                       |
   | delete local copy, show "saved"      |                       |                       |
   |                                      |      claim job ------>|                       |
   |                                      |                       |-- OCR + describe ---->|
   |                                      |                       |<-- text, kind --------|
   |                                      |                       |-- summarise --------->|
   |                                      |                       |<-- kind, title, tags -|
   |                                      |                       | chunk + embed (local) |
   |                                      |                       |-- redraw (parallel) ->|
   |                                      |                       |<-- .excalidraw -------|
   |-- GET /api/captures?since ---------->|                       |                       |
   |<-- states, page link ----------------|                       |                       |
```

### Background jobs

Each job does one step and enqueues the next, so a failure retries only that step.

| Job | Does | Writes |
| --- | --- | --- |
| `extract` | Photo or file: one Claude vision call on a downscaled JPEG copy (the original, often a multi-MB HEIC, is untouched) returns text, a description and a kind (whiteboard, document, screenshot, photo). Whiteboard and document set the page kind; whiteboard enqueues `redraw`. URL: fetch readable text. Note: nothing. Every capture type then enqueues `summarise`. | `ocr`, `description`, `fetched` |
| `redraw` | Whiteboard only: Claude produces an Excalidraw scene from the photo, checked to parse as Excalidraw JSON before saving | `excalidraw` |
| `summarise` | One Claude call returns kind, `fields`, summary, title and tags, applied under the title, slug and kind rules above. | page kind, `fields` and tags, then `summary`; rev |
| `index` | Re-chunk the page and its derived text, embed locally, re-parse links | `chunk`, `chunk_fts`, `chunk_vec`, `link` |

`redraw` runs in parallel; nothing waits for it and its failure leaves the page intact. Page edits
also enqueue `index`.

**States.** `queued` -> `running` -> `done`. On error the job goes back to `queued` with
`run_after = now + 2^attempts minutes`; after five attempts it is `dead`. A job left `running` by a
crash is requeued at start-up. If a job's page is deleted mid-run, the cascade removes the job
row, and the worker treats that as finished, not as an error.

**Failure visibility.** The recent strip shows each capture as queued, saved, processing, done or
failed (a dead job), with `last_error` and a *retry* button. The original and the page already
exist, so nothing is lost; if `summarise` fails, the kind stays as the user chose or `extract` left it,
else `note`.

## Images in the text

Every page is Markdown with its images embedded (#48). A photo capture's page text is its text,
if any, then one `![](/api/blobs/<sha>/preview?size=2048)` per image, in order; from then on the
text is the user's: ingest never touches it, and reprocessing only adds derived versions. The PWA
shows each embedded image of this server's files where the text puts it, as a figure: a tap opens
the photo viewer (every image of the page, in order), and its caption has the file's name,
Download and *Ask Claude*, which queues ingest for that one image (on any capture holding it,
not only photo captures). Once queued it is the photo's panel instead: its state, then what
Claude read, described and drew. Below the text are only the files it doesn't embed (PDFs, or
photos of pages made before this). Images on lines of their own (one or several in a row) become
figures; one in a link, heading, list or quote, or beside text, stays a plain image, and its file
is listed below the text as well. A page's download (and `scrap export`) points the text's images
and links at the files beside it (never inside code) and doesn't list a shown image again. Share
leaves out lines that only embed images. The figure code is a lazy chunk, outside the app shell.

## Excalidraw

The photo and its derived drawing are shown side by side. The PWA embeds the Excalidraw React
component to view and edit the drawing. Saving an edit overwrites the `excalidraw` row with producer
`human`, and regenerating asks before replacing a human edit.

## MCP tools

Served at `/mcp` by the official MCP SDK inside the FastAPI app (Streamable HTTP, stateless,
JSON replies), so a session adds it with one `claude mcp add --transport http` line and nothing
local, and it works the same behind the cluster's ingress. A stdio `scrap mcp` command was the
alternative: it needs a shell where the database is (inside the container), which no client
session has. Tools and limits: [](../reference/mcp.md).

- `search`, `read`, `recent`, `todos`, `tags`: thin wrappers over the store; `search` takes the
  search box's syntax. Results carry each page's PWA URL (`$SCRAP_PUBLIC_URL/p/<slug>`) and its
  images as URLs, so Claude links there instead of trying to show them. Page text is returned in
  JSON fields, as data.
- `write` only adds: a new page, or a section appended to a page written over MCP. Provenance is
  the capture's source `mcp` (which clients of the HTTP API cannot send), author `claude`, and a
  free-text `fields.origin`; no migration was needed. The PWA shows a badge; `is:claude` filters.
  A client key is hashed into the capture id, the store's existing retry key.
- Deferred: `ingest` (a URL or text as a capture), a `context` tool for a photo's stored model
  run, deleting, setting a kind and ticking a todo (PWA actions).

## Security posture

- **Tailnet only.** Serve is the only way in and Funnel stays off. The tailnet policy grants the
  scrap device to the owner's own devices only; tagged servers (for example any internet-facing
  box) must not be able to reach it. The service listens on loopback, so only Serve can set the
  identity headers.
- **Identity is attribution, not the gate.** The ACL is the gate. `author` is the
  `Tailscale-User-Login` header. Tagged devices send none, so their requests are recorded with the
  fallback author `tagged`.
- **What it holds.** Its database, files and Claude credential. No cluster or git credentials
  (service-account token automount off), no shell tools.
- **Prompt injection.** Ingested content is untrusted data. Ingest calls Claude with a fixed prompt
  and checks the output against a schema. It gets no shell and no cluster credentials; an image call
  gets only the Read tool, in a throwaway directory holding that one file. The Claude credentials
  share its container, so the call never bypasses permissions and a deny rule covers their
  directory; this confinement is verified when the worker is built. The worst outcome is a wrong
  page, which `page_rev` can undo. URL fetching refuses private and tailnet addresses, re-checked
  after DNS resolution and after every redirect.
- **Reading is not acting.** Sessions holding cluster or other powerful credentials should not
  mount the scrap MCP server, since pages may hold injected text.

## Implementation notes (M1)

Where the code so far differs from the text above; later milestones should build on these.

- **Soft delete.** `page.deleted_at` marks the trash and `POST /api/pages/{id}/undelete` undoes it;
  nothing is purged yet. So the cascades above never fire on delete: jobs, links, `summarise` and
  `[[slug]]` resolution must check `deleted_at` themselves, and a trashed page keeps its slug.
- **Index.** One chunk per page (title and body), written in the same transaction as the capture or
  edit rather than by an `index` job; `chunk` has no `derived_id` until `derived` exists.
- **Titles.** The first line of the capture's text, else the URL, else the device date.
- **Lookup.** The API takes a page's id or its slug.
- **Export.** `scrap export` (from v0.1 below) is in M1, without tags until tags exist.
- **PWA.** Vanilla TypeScript built by Vite into the Python package (`scrap/static`), no UI
  framework until the Excalidraw view needs React. The service worker precaches the app shell
  only and also catches the share target's POST, queueing it in IndexedDB like any capture; the
  server's `POST /share` is a fallback if it does not. No per-capture processing states yet (there
  are no jobs): the capture screen shows what is still on the phone and the newest pages. Todos,
  Consume and Inbox views wait for the worker. `GET /api/pages` gained `thumb`.

## Import (M2)

`scrap import` brings in a Thoth vault ([how-to](../how-to/import-a-vault.md)) through `Store`,
so revisions and the search index stay consistent. Each page keeps the vault's dates (its
`created_at`, `updated_at` and revision 1), kind (fixed), fields and tags; its capture has source
`import`, the vault file as its text (which also keeps ingest from retitling it) and the page's
images, PDFs in a second `file` capture. The capture id is made from the page's path, so a second
run skips pages already imported. Links between pages become `[[slug|label]]`, which the PWA
renders as links to `/p/<slug>` (the `link` table does not exist yet); images are embedded as
`![](/api/blobs/<sha>/preview?size=2048)`, as a photo capture's are. Dates alone become noon
UTC. A rerun never updates a page already imported.

The search index holds the labels of links and images, not their addresses (for every page, not
only imported ones), so `/api/blobs/...` and URLs in Markdown links (`<...>` addresses too) are
not words to find: a hand-written link is found by its text, not its domain, by choice.

### Markdown (#71)

Page text is Markdown, parsed by a library on both sides with the same grammar: CommonMark plus
GitHub's tables, strikethrough and footnotes, `[[slug|label]]` page links, raw HTML as text and
a line break kept as one. The PWA renders it with markdown-it (task lists, bare `https://` links
and heading ids too) in `render.ts`, a lazy chunk the service worker keeps for offline use, so
the app shell stays within its 15 kB budget; the page view loads it while it fetches the page,
and without it (offline before it was kept) shows the text as typed. A post-parse pass allows
only http(s), mailto, page and in-page links (opened with `rel=noopener`), and only this server's
own images, each marked with its `data-sha` for `figure.ts`. A ` ```mermaid ` block is drawn by
Mermaid, a separate chunk loaded only for a page that has one (not kept offline: it is big), with
`securityLevel: 'strict'`; it is bundled, not loaded from a CDN, so the CSP needs no change.

The server parses with markdown-it-py (`scrap/markdown.py`, with mdit-py-plugins for footnotes):
the search index holds plain text from the parse (link and image text, not addresses; a page
link's label; code as typed; a table's cells; no markup), and the importer rewrites links,
images and wiki links found by the parse, mapped back to their place in the text, so code is
never rewritten and a link in a table cell escapes its pipe. Both parsers are linear in the
text (markdown-it-py does about 300 kB a second on normal text, a tenth of that on a megabyte
of brackets). Migration 0004 re-indexed every page this way.

## Claude ingest (M2)

Claude ingest is designed in [ingest](ingest.md), which supersedes these parts of the text above:
M2 calls the Messages API only, with no tools (no `claude -p` backend, no Read tool); one
combined `ingest` job per photo replaces `extract`, `redraw` and `summarise`, and derived text is
indexed by triggers rather than an `index` job; job retries follow its error classes (outages
and spend limits pause the queue without failing jobs; any other failure is charged, three kill)
instead of five attempts with doubling delays; `derived` keeps versions (newest current) instead
of overwriting, so a human drawing edit is a new version; the provisional title is replaced
without a new revision and the slug never changes; only photos are ingested in M2 (no URL
fetch); and old derived rows arrive in M2, not v0.1.

## Deferred to v0.1

- Voice memos (needs a transcriber).
- Background Sync for the upload queue.
- Filing captures into existing pages, and automatic cross-linking.
- Markdown export (one `<slug>.md` per page, attachments beside it; never read back as the store).
- A `namespace` column for read scoping by less trusted surfaces.
- Keeping old derived rows on regeneration, with pruning.
- A status page for dead jobs.
- `scrap gc` to sweep orphan blobs (left by deleted pages).
- A per-capture *keep a copy* switch (default off) that keeps a consume item's fetched text, for
  pages that may vanish or sit behind a paywall.

## Deferred, larger

- **Work browser route.** A Cloudflare tunnel plus Access (passkey-capable IdP, short sessions) in
  front of the PWA only; the service verifies the Access JWT itself. Cloudflare sees plaintext.
- **Work sandbox.** Userspace Tailscale (no root, no TUN), an ephemeral tagged key, an ACL to the
  MCP port only; scoped `search` and `read`, inbox-only writes.
- **PKM session pod.** A remote Claude Code session in the cluster with only the scrap MCP server.
- **Separate ingest worker.** The same image with another command, if LLM work needs isolating.

## Open questions

- **Headless terms.** Confirm current terms permit unattended `claude -p` before relying on it.
- **Audio transcription** (for voice in v0.1). Local faster-whisper or a hosted API.
- **Embedding model.** bge-small or nomic-embed-text, decided on a test set of real captures.
- **Postgres and pgvector**, only if SQLite is outgrown.
- **Cloudflare route auth.** Which identity provider and session length; capture or view only.
- **Work sandbox scope.** Namespaced reads or full read; whether work material gets a namespace.
- **Tailscale Kubernetes operator.** Whether its ingress passes the identity headers through, or a
  `tailscale serve` sidecar is needed (assumed above).
