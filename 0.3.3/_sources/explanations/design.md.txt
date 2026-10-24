# scrap design

Status: built through milestone 2 (capture, search, kinds and todos, revisions, Claude ingest of
photos, drawings, MCP, import, gc, backup and export) plus Claude's reading of text pages
(enrich). This page describes scrap as built. It keeps the ideas of an earlier, much larger system
(classified pages, semantic recall, MCP tools) and drops its machinery (a git-synced vault, a
chat-bot daemon, a stack of paid-API integrations). The [decision records](decisions.md) give the
reasons, and where one says it supersedes the first design, the record wins.

**Changed from the first design:**

- Search is FTS5 only. There are no embeddings, no `sqlite-vec`, no `meta` table and no `scrap
  reindex` ([](decisions/0008-search-fts5-only-for-now.md)).
- Claude is called through the Messages API with no tools, one structured call per photo. There is
  no `claude -p` backend and no Read tool. The `extract`, `redraw`, `summarise` and `index` jobs
  became one `ingest` job; failures pause the queue instead of burning five retries
  ([](decisions/0009-claude-ingest-via-messages-api.md),
  [](decisions/0010-job-queue-pauses-instead-of-failing.md)).
- Deleting a page moves it to the trash. Nothing is purged, so there is no cascade on delete.
- Derived results are versioned rather than overwritten
  ([](decisions/0011-drawings-as-skeletons-excalidraw.md)).
- There is no `link` table: links and backlinks are read from the page text.
- Deployment is rootless podman units for one server (listening on a Unix socket by default) or a
  Helm chart, not a k3s sidecar ([](decisions/0016-deployment-single-server-and-helm.md),
  [](decisions/0018-unix-socket-for-single-server-installs.md)). Tailscale Serve is still the way in
  ([](decisions/0007-tailscale-serve-for-access-and-identity.md)).

## Principles

1. **Tiny.** One process, one database file, one folder of files. If a feature needs a second
   service, it waits ([](decisions/0003-one-process-sqlite-and-a-folder.md)).
2. **Off the shelf.** Claude does the reading and writing that needs judgement. SQLite does storage
   and search. Tailscale does networking and identity. Excalidraw does drawings. scrap is the glue.
3. **Originals are kept, everything else is derived** and can be regenerated, except a saved
   link's article, which is fetched to be read and not stored. The search index is disposable and
   is rebuilt by a migration, not a command. Deleting a page moves it to the trash and keeps its
   captures and files; only `scrap gc` removes files nothing refers to
   ([](decisions/0004-originals-kept-everything-else-derived.md)).
4. **Capture never waits.** Saving is a file write and a few row inserts; anything slow runs later
   in the background ([](decisions/0005-capture-never-waits.md)).
5. **Claude reasons, the PWA shows.** Claude (over MCP) is for asking and writing; the PWA is for
   capturing and looking. Answers link into the PWA.

## What is built

- **One Python process.** FastAPI serves the built PWA, its JSON API and an MCP server (streamable
  HTTP). One worker thread, started from the FastAPI lifespan, runs the Claude jobs. It runs only
  when `SCRAP_INGEST=on` (the default is off); capture, search and everything else work without
  it.
- **Storage.** SQLite in WAL mode and a `files/` folder keyed by SHA-256, on one persistent volume.
  Backup is a SQLite online backup plus a copy of `files/`. The API and the worker both write, so
  every connection runs `PRAGMA foreign_keys = ON` and `PRAGMA busy_timeout = 5000` on open,
  outside any transaction. The cascading foreign keys are a safety net for a future purge; today a
  delete only sets `page.deleted_at`.
- **Capture.** Notes, links, photos and files, from a phone-first PWA with an offline queue and an
  Android share target ([](decisions/0006-vanilla-typescript-pwa-with-lazy-chunks.md)).
- **Search.** SQLite FTS5 with one query syntax shared by the PWA and MCP (see
  [Search](#search)).
- **Kinds, todos and revisions.** Pages have a kind, flat fields, tags, task boxes and, for todos,
  a due date, priority and snooze ([](decisions/0012-kinds-flat-fields-and-typed-todo-columns.md),
  [](decisions/0019-kinds-and-tags-editable-with-revisions.md)).
- **Claude.** Photo ingest with drawings, text enrich, related pages and a daily budget (see
  [Claude features](#claude-features)).
- **MCP.** Search, read and write tools served at `/mcp`
  ([](decisions/0013-mcp-server-inside-the-app.md)).
- **Keeping and moving data.** Import of a Thoth vault, `scrap backup`, `restore`, `export` and
  `gc` ([](decisions/0017-thoth-vault-import-through-the-store.md),
  [](decisions/0015-images-in-text-and-gc.md)).
- **Access.** No login code. Tailscale Serve is the recommended way in (Funnel stays off); on
  Kubernetes a proxy such as Cloudflare Access fronts it, with an optional bearer token on `/mcp`
  ([](decisions/0023-bearer-token-on-mcp-and-an-identity-header-setting.md)). See
  [Scope and stack](overview.md).
- **Deployment.** A multi-arch image (`linux/amd64`, `linux/arm64`) run either under rootless
  podman and systemd on one server ([](../how-to/deploy-single-server.md)) or by the Helm chart on
  Kubernetes ([](../how-to/deploy-kubernetes.md)).

**One capture is one page.** Each capture creates its own page at once.

- A *note*: the text is the body, and its first line (without any leading `#` of a heading, at
  most 200 characters) is the title. A note whose whole text is a bare URL is a link instead.
- A *link*: the body is the URL, followed by any text given with it. The title is the URL, or the
  first line of that text if there is any.
- A *photo*: the body is the capture's text, if any, then one image embed per image (see
  [Images in the text](#images-in-the-text)). The title is the text's first line, else the time on
  the device (`YYYY-MM-DD HH:MM`), which photo ingest replaces if there is no text.
- A *file* capture (the files include something that is not an image, such as a PDF): the body is
  the capture's text, if any, with an embed for any image among the files. With no text the title
  is the device time.

Claude then adds derived text, a better title, tags and a summary. Merging and cross-linking pages
come later, by hand or through MCP `write`. Ingest stays a fixed pipeline with no search-then-decide
loop.

## Data model

The source of truth is **captures** (what arrived), **blobs** (the bytes) and **pages** (what you
read and edit). **Derived** rows cost an LLM call to remake, so they are stored. **Chunks and the
search indexes** are a cache. The schema is the numbered scripts in `src/scrap/migrations/`;
this is the core of it as built:

```sql
PRAGMA foreign_keys = ON;  -- per connection: the app sets it on every open

-- Bytes of every original and binary derived artifact, at files/<sha[0:2]>/<sha>.
CREATE TABLE blob (
    sha256      TEXT PRIMARY KEY,
    mime        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE page (
    id          TEXT PRIMARY KEY,              -- ULID
    slug        TEXT NOT NULL UNIQUE,          -- made from the title at creation, never changes
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',      -- Markdown, may contain [[slug]] links
    kind        TEXT NOT NULL DEFAULT 'note' CHECK (kind IN ('note', 'todo', 'consume',
                  'memory', 'reference', 'whiteboard', 'document')),
    kind_fixed  INTEGER NOT NULL DEFAULT 0 CHECK (kind_fixed IN (0, 1)),  -- 1: the user chose it
    fields      TEXT NOT NULL DEFAULT '{}' CHECK (json_type(fields) = 'object'),  -- flat
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT,                          -- set: in the trash
    due         TEXT,                          -- a todo's, YYYY-MM-DD   (migration 5)
    priority    TEXT,                          -- a todo's, high|medium|low   (migration 5)
    snoozed_until TEXT,                        -- a todo's, YYYY-MM-DD   (migration 6)
    task_done   INTEGER NOT NULL DEFAULT 0,    -- task boxes ticked   (migration 7)
    task_total  INTEGER NOT NULL DEFAULT 0     -- task boxes in all
);

-- Rev 1 is written at creation; every title or body change adds one (MCP's edit_page
-- folds a quick burst into one, with a new number: see ADR 22).
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
    tag         TEXT NOT NULL CHECK (tag = lower(tag) AND length(tag) BETWEEN 1 AND 64),
    PRIMARY KEY (page_id, tag)                 -- '/' allowed in a tag
);

CREATE TABLE capture (
    id          TEXT PRIMARY KEY,              -- ULID minted by the client: the retry key
    kind        TEXT NOT NULL CHECK (kind IN ('photo', 'note', 'url', 'file')),
    text        TEXT,
    url         TEXT,
    source      TEXT NOT NULL,                 -- 'pwa', 'share', 'mcp' or 'import'
    author      TEXT NOT NULL,
    created_at  TEXT NOT NULL,                 -- on the device
    received_at TEXT NOT NULL,                 -- on the server
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE
);

CREATE TABLE capture_blob (
    capture_id  TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    sha256      TEXT NOT NULL REFERENCES blob(sha256),
    filename    TEXT,
    PRIMARY KEY (capture_id, ord)
);

-- What Claude made of a photo, as versions: one current row (superseded_at IS NULL) per
-- (capture, photo, kind). Rows never change; a new current one supersedes the old.
CREATE TABLE derived (
    id            INTEGER PRIMARY KEY,
    capture_id    TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    source_sha256 TEXT NOT NULL DEFAULT '',
    kind          TEXT NOT NULL CHECK (kind IN
                    ('ocr', 'description', 'summary', 'fetched', 'excalidraw')),
    version       INTEGER NOT NULL CHECK (version >= 1),
    producer      TEXT NOT NULL,               -- model id, or 'human'
    run_id        INTEGER REFERENCES model_run(id),  -- the call that made it; NULL if human
    author        TEXT,                        -- of a human version
    text          TEXT,                        -- indexed while current
    data          TEXT CHECK (json_valid(data)),  -- excalidraw: {"format", "width", "height", "elements"}
    superseded_at TEXT,                        -- NULL: the current version
    created_at    TEXT NOT NULL,
    UNIQUE (capture_id, source_sha256, kind, version)
);

-- ---- Index: a cache, rebuilt from page and derived. ----

-- Chunks are never updated: delete and insert.
CREATE TABLE chunk (
    id          INTEGER PRIMARY KEY,
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    text        TEXT NOT NULL,
    derived_id  INTEGER REFERENCES derived(id) ON DELETE CASCADE,  -- NULL: the page's own
    title       TEXT NOT NULL DEFAULT '',      -- the page's own chunk only, with tags and summary
    tags        TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT ''
);

CREATE VIRTUAL TABLE chunk_fts USING fts5(
    title, tags, summary, text, content='chunk', content_rowid='id',
    tokenize='porter unicode61'
);
```

The `chunk_ai` and `chunk_ad` triggers keep `chunk_fts` in step with `chunk`, including cascaded
deletes, and `chunk_bu` refuses an `UPDATE`. Not shown: the `CHECK`s on `due`, `priority` and
`snoozed_until`, the immutability and supersede triggers on `derived`, and the indexes.

Notes:

- **IDs** are ULIDs as text, safe to mint on the phone. Times are ISO 8601 UTC. Blobs are
  content-addressed, so a photo shared twice is stored once.
- **Derived** rows sit beside the untouched original and are versions. A new current version
  supersedes the old by trigger (`derived_supersede`); another trigger refuses to change a
  version, and a superseded one stays superseded, so Restore inserts a copy. Never
  `INSERT OR REPLACE` into `derived` or `chunk`: REPLACE deletes without firing `chunk_ad`. Only
  `ocr`, `description` and `excalidraw` are written; `summary` and `fetched` are allowed by the
  `CHECK` but reserved.
- **One own chunk per page.** A page has exactly one chunk of its own (`ord` 0, `derived_id` NULL)
  with the columns title, tags, summary and text, where text is the body as plain words
  (`markdown.plain`). It is rebuilt inside the same write transaction as any capture, save, tag
  change or enrich result, so there is no index job. Each *current* derived text (OCR, a photo's
  description, a human drawing's labels) is a further chunk, made by the `derived_index` trigger
  when the version is inserted and deleted by `derived_unindex` when it is superseded.
- **What is indexed** is text only: the title, the tags, the summary, the body as plain text, and
  the current OCR and description of each photo. The summary is the page's `summary` field if it
  has one (an import's or the user's), else Claude's enrichment summary. Fetched article text is
  not stored and so not indexed. Not pixels, and not raw Excalidraw JSON (coordinates and IDs).

### Tables beyond the core

| Table | For |
| --- | --- |
| `page_meta_rev` | Revisions of a page's kind and tags (migration 8); see [Revisions and conflicts](#revisions-and-conflicts) |
| `job` | One `ingest` job per photo; `state` `queued`, `running`, `done` or `dead`, `failures`, `run_after`, `last_error` (migration 2) |
| `queue_state` | One row: whether the Claude queue is paused, until when and why (`auth`, `credit`, `outage`, `budget`) |
| `model_run` | Every photo call: request, response blocks, sanitised output, usage, `cost_microusd`, error class; the JPEG sent is kept as a blob |
| `enrich_job`, `enrich_run` | The same for text pages (migration 9): one queued job per page, and every call with its cost |
| `enrichment` | A page's Claude summary and, for a link, the fetched address and title |
| `model_tag` | Which tags Claude added (`on`), and which the user took off (`off`: never added again) |
| `related` | The pages Claude picked as related to each page, in order |

### Migrations

Scripts are numbered, and script *N* sets `PRAGMA user_version = N`. `migrate()` takes an
exclusive `flock` on `db.lock` so two processes cannot migrate at once, turns on WAL, and applies
each missing script in one transaction. A migration can have a Python step in `store.AFTER`, run in
that same transaction after its script: migrations 3 and 4 re-index every page with `index_all`
(that is how the search index is rebuilt), 5 moves an import's `due` and `priority` fields into
their columns, and 7 counts every page's task boxes. Migrations 6 to 9 are additive (their Python
step adds a column or table only if it is missing), so an older scrap still runs on a newer
database if you set `user_version` back to its own. A database newer than the code is refused, as
is a backup newer than the code on restore.

### Page identity, links, tags

- **Identity.** The ULID. The slug is made from the title when the page is created (ASCII,
  lower-case, hyphens, at most 60 characters, `-2`, `-3` on collision) and never changes, so
  `[[slug]]` links survive renames, at the cost of a slug that drifts from the title. A trashed
  page keeps its slug, so slugs are never reused. The API takes a page's id or its slug.
- **Titles.** Two rules replace a provisional title, and neither makes a revision or touches the
  slug. Photo ingest replaces it once, only while it is still the title of rev 1 with no later
  revision, the capture has no text, and the photo is the capture's first. Enrich replaces a saved
  link's title only while it is still the URL as captured ([](ingest.md)). A title the user edits
  is never replaced.
- **Links.** `[[slug]]` or `[[slug|label]]` in Markdown, read from the body when needed; there is no
  `link` table. Outgoing links come from scanning the body, and backlinks from an `instr()` scan of
  the bodies of pages not in the trash. That is fine at single-user scale, and an index is the
  upgrade path. Dangling links are allowed.
- **Tags.** Flat, lower-case, `/` allowed. The PWA edits them. Claude's (photo ingest, and enrich
  for text pages: [](ingest.md)) are marked in `model_tag` and shown dashed; a tag the user takes
  off is never added back, and Claude never removes one.
- **Related.** Enrich stores the pages Claude picked as related apart from the text (a nightly
  pass and Ask Claude, not every save); the page shows them as Related both ways, merged with
  backlinks.

### Kinds

A page's `kind` is `note` (default and fallback), `todo`, `consume` (to read, watch or listen to),
`memory`, `reference`, `whiteboard` or `document`. scrap classifies and summarises; it never
rewrites the user's words or fits them to templates.

- **`fields`** is a flat JSON object (no nulls, no nested values, at most 32 fields, a kind's defaults added only while there is room; numbers finite and within ±2^53, the most a browser holds exactly), not per-kind
  tables. In use: `status` on todo and consume, `subtype` (`read`, `watch`, `listen`) and `source`
  (the link) on consume, `summary` (an import's or the user's, which wins over Claude's in the
  index) and `origin` (where a page written over MCP came from).
- **A todo's due date, priority and snooze** are typed columns of `page`, not fields, so `due:`
  and `priority:` filters and `sort:due` / `sort:priority` are plain indexed SQL
  ([issue 104](https://github.com/gilesknap/scrap/issues/104)). `due` is a calendar day
  (`YYYY-MM-DD`, no time, no time zone: "today" is the server's local day in searches and the
  phone's on rows); `priority` is `high`, `medium` or `low` (three: enough to sort by, few enough
  to pick without thinking; Thoth's `urgent` imports as `high`). `snoozed_until` is a day too: a
  snoozed todo is left out of Now and of the Todos count until then, and `is:snoozed` finds it.
  They belong to the todo kind: the API refuses them on another, and a todo made a note keeps them
  (a stray tap loses nothing) but they are ignored (not returned, filtered, sorted or exported)
  until it is a todo again. Setting them is like ticking: not a revision, no new `updated_at`. The
  Markdown download and export write them as front matter, so a page stays portable. Deliberately
  out: recurring tasks, sub-tasks and projects (that is a task app).
- **Task boxes.** Task list items (`- [ ]`, `- [x]`) in the body are counted per page
  (`task_done`, `task_total`) whatever its kind. A note nobody filed (`kind_fixed` 0) that has
  boxes becomes a todo, filed as a new capture of that text would be. On a todo, ticking the last
  box marks it done, and unticking one (or adding an unticked one) reopens a todo that was done
  with all boxes ticked. A `cancelled` todo is left alone, and a status set by hand in the same
  edit wins. None of it is a revision.
  Claude can add the boxes: when photo ingest or text enrich reads an unfixed note as a list of
  actions, with high confidence, and it has no boxes yet, one text revision by `claude` appends
  `- [ ] item` lines below the user's text, and this rule then files it as a todo
  ([](decisions/0026-claude-appends-task-boxes-to-a-list-of-actions.md)).
- **Status** is one lifecycle for todo and consume, Thoth's: `open`, `in_progress`, `done`,
  `cancelled`. New pages start `open`; ticking a todo toggles `open` and `done`, and the other two
  are stored and shown (set by an import, richer controls later).
- **Choosing a kind.** The capture buttons (camera, gallery, note) only choose the input; the
  kind is chosen in the PWA's editor, for a new capture or an existing page, from Note
  (default), Todo, Later (`consume`), Whiteboard and Document (`memory` and `reference` are not
  offered until wanted; a hard-coded list until real use asks for configurable kinds). A bare
  URL pre-selects Later; photos skip the choice (ingest classifies them; the user can change it).
  The capture's `kind` field or `PATCH /api/pages/{id}` sets it.
- **A kind the user changes** (PWA edit, `PATCH`) **keeps every field** the page has (a summary,
  a due date, an imported status: a stray tap on a chip must lose nothing) and adds the new
  kind's defaults for the keys it lacks. So todo -> note -> todo comes back as it was, and a
  status or subtype carried over keeps its value. The defaults are todo `{"status":"open"}` and
  consume `{"subtype":"read","status":"open"}` plus `source`, the capture's own URL (omitted if it
  has none).
- **The user wins.** A kind chosen at capture or in the editor sets `kind_fixed`, and nothing
  else changes a fixed kind. Four other paths set a kind, each only while the page is an unfixed
  `note`:
  - photo ingest: a `whiteboard` or `diagram` image makes the page a `whiteboard`, a `document`
    image a `document` (other image kinds change nothing);
  - enrich: a saved link becomes Later (`consume`, with its defaults and `source`);
  - task boxes make it a todo (above);
  - an import sets the kind and fixes it.
- **Views.** One list screen (Search; `/recent` redirects to it): an empty box lists every page
  newest first, a fixed kind row (All, Notes, Todos, Later, Boards, Docs) sets or clears `kind:`,
  and the query rides in the address (`/search?q=...`). The Todos screen lists what to do now (open
  and not snoozed) first. A todo's page has Mark done and Reopen, setting `fields.status`. There is
  no Inbox: `kind_fixed` is only for the user-wins rule.

(revisions-and-conflicts)=
### Revisions and conflicts

Text and metadata have separate histories.

- **Text revisions** (`page_rev`): a change of title or body adds one. A `PATCH` that changes either
  must send `base_rev`, the revision the edit started from, and gets `409` with the current `rev`
  if it is stale, saving nothing. A title equal to the title at `base_rev` counts as unchanged, so a client that sends back
  the title it loaded never undoes a title Claude set meanwhile. A page's text is at most 1 MB.
- **Metadata revisions** (`page_meta_rev`): each change to a page's kind or tags, by the user in
  the PWA or by Claude over MCP, records the kind and tags before and after. One author's changes
  within `SCRAP_REVISION_WINDOW` (300 s by default) fold into one revision. MCP `revisions` lists
  both kinds, and `revert` undoes a metadata revision or a whole bulk change by its batch id
  ([](decisions/0019-kinds-and-tags-editable-with-revisions.md)).
- **Not revisions:** `fields` (status), due date, priority and snooze, task counts, and a
  provisional title replaced by ingest or enrich.

## Search

Search is SQLite FTS5 (`porter unicode61`) over the chunks above. Every word of a query must match
somewhere in the page, as a prefix, wherever it stands in the query. Pages with every word in the
title rank first, then those with every word in the title, tags or summary, then by `bm25` with
column weights 10, 5, 3, 1 (title, tags, summary, text), so a short body that says a word twice
does not beat a long page tagged with it. Hits are grouped by page (a page's best chunk wins,
because `bm25()` and `snippet()` refuse `GROUP BY`, so it is done in Python). One parser,
`query.py`, serves the PWA's search box and MCP, with filters such as `kind:`, `tag:`, `is:`,
`has:`, `image:`, `due:`, `priority:`, `after:` / `before:` and `sort:`; the full syntax is under
`GET /api/search` in [](../reference/api.md). The PWA's facets and tag browsing come from the same
code. The title, tags and summary columns are why ranking can weigh them
([issue 84](https://github.com/gilesknap/scrap/issues/84)).

## Phone quick capture

1. **Tap the icon.** The installed PWA opens from the service worker cache, even offline, on the
   capture screen: camera, gallery and note buttons (how to capture; the kind is chosen in the
   composer), what is still waiting on the phone, and the newest pages.
2. **Choose an input.**
   - *Camera*: `<input type="file" accept="image/*" capture="environment">`, or the gallery;
     several shots can go into one capture.
   - *Note*: a text box.
   - *Share*: the manifest's `share_target` takes URLs, text and files from the share sheet. It
     works for installed PWAs on Android, not iOS (where a Shortcut could post to the API).
     Android often sends a link as `text`, so the server lifts a bare URL in `text` into `url`.
3. **Save.** The client mints a ULID, stores the capture in IndexedDB and shows it as *queued*.
4. **Upload.** The app posts it to `POST /api/captures` and deletes the local copy on success. On
   failure it stays queued and retries with backoff while the app is open, and on next open. A
   capture that is waiting or failed shows on the capture screen with *Retry* (and *Split and
   retry* for one with several files).
5. **Store.** The server writes the files to `files/`, then in one `BEGIN IMMEDIATE` transaction
   looks up the capture id (found: a retry, return `200`), else inserts blobs (`ON CONFLICT DO
   NOTHING`), the page (before the capture, for the foreign key; a chosen kind sets `kind`,
   `kind_fixed` and default `fields`), `page_rev` 1, the capture, `capture_blob`, the tags, the
   page's search chunk, and an `ingest` job per distinct image of a photo capture. A note or link
   also gets an `enrich_job` when enrich is on: a link at once, a note after the debounce. It
   returns `201`. No LLM call is on this path, so the note or title is searchable even if Claude
   is down.
6. **Process.** The worker, if ingest is on, runs the jobs. The page view polls `GET
   /api/pages/{id}` and `GET /api/ingest` every 10 seconds while a photo of that page is queued or
   processing, so it shows the result when it lands.

```text
Phone (PWA)                           scrap API                 worker (if on)           Claude
   |                                      |                          |                       |
   | save -> IndexedDB, show "queued"     |                          |                       |
   |-- POST /api/captures (ULID) -------->|                          |                       |
   |                                      | page, rev 1, capture,    |                       |
   |                                      | search chunk, ingest and |                       |
   |                                      | enrich jobs              |                       |
   |<----------------- 201 ---------------|                          |                       |
   | delete local copy                    |        claim job ------->|                       |
   |                                      |                          |-- one call ---------->|
   |                                      |                          |<-- structured JSON ---|
   |                                      |   derived versions, title, tags, kind, chunks    |
   |-- GET /api/pages/{id}, /api/ingest ->|  (while a photo is busy) |                       |
   |<-- page with ingest state -----------|                          |                       |
```

What the user sees of a photo's progress is on its page: *queued*, *processing*, *done*, *failed*
(with the reason and a *Retry*) or *paused* (with a *Resume* banner while the queue is paused).
The original and the page already exist, so nothing is lost when a job fails.

(claude-features)=
## Claude features

All Claude work is behind `SCRAP_INGEST=on` (default off) and `ANTHROPIC_API_KEY`; the details and
the rules are in [](ingest.md) and are not repeated here.

**Calling Claude.** One function, `claude.complete()`, makes one Messages API request with no
tools and a JSON schema for the output. It never retries: the queue does, so one claim is one call.
The key comes from `ANTHROPIC_API_KEY`. Photos go to `SCRAP_VISION_MODEL` (default
`claude-opus-5-5`) and text pages to `SCRAP_TEXT_MODEL` (default `claude-haiku-5-5`, effort
`SCRAP_TEXT_EFFORT`, default `low`). The cost of every call is recorded. There is no other backend.

**Photo ingest.** An `ingest` job per distinct image of a photo capture sends a JPEG made from it
and gets back, in one call, the text (OCR), a description, the image kind, a title, tags and
Excalidraw skeleton elements for a board or diagram. These are saved as derived versions and the
title, tags and kind rules above applied. The image kinds are `whiteboard`, `handwriting`,
`diagram`, `screenshot`, `document`, `photo` and `other`. The drawing is the elements the model
returned, sanitised and checked (`sanitise.py`) and saved as the derived kind `excalidraw`, with
the JSON in `derived.data`; there is no separate redraw job.

**Text enrich.** An `enrich_job` per text page gets tags and a summary from a small model, and for
a saved link its title as well; the link is fetched first, under strict address checks
(`fetch.py`), and the fetched text is sent but not kept. A note is read after
`SCRAP_ENRICH_DEBOUNCE` seconds (default 60; each save moves it later) so a burst of edits makes
one call, a link at once. `SCRAP_ENRICH=off` keeps Claude to photos. Nothing edits the page's text.

**Related pages.** A separate call per page picks up to five related pages from a numbered
candidate list, on *Ask Claude* at once and otherwise in the nightly pass, `scrap enrich
--related`, for pages changed since their last picks.

**Queue and budget.** One worker thread wakes every 30 seconds or when a job is queued, and runs one
job at a time. Outages, spend limits and a bad key pause the queue without failing jobs; any other
failure is charged to the job, retried 10 minutes later (invalid output at once), and the job is
`dead` on the third. A job found `running` at start-up is charged as crashed. A daily budget
(`SCRAP_BUDGET_DAY_USD`, default $3, from recorded usage and counting photos, text pages and
related calls together) pauses the queue until UTC midnight. The first pause of an episode POSTs
once to `SCRAP_NOTIFY_URL`, if set. `/healthz` returns `503` if ingest is on and the worker thread
has died.

(images-in-the-text)=
## Images in the text

Every page is Markdown with its images embedded
([issue 48](https://github.com/gilesknap/scrap/issues/48)). A photo capture's page text is its
text, if any, then one `![](/api/blobs/<sha>/preview?size=2048)` per image, in order; from then on
the text is the user's: ingest never touches it, and reprocessing only adds derived versions. The
PWA shows each embedded image of this server's files where the text puts it, as a figure: a tap
opens the photo viewer (every image of the page, in order), and its caption has the file's name,
Download and *Ask Claude*, which queues ingest for that one image (on any capture holding it,
not only photo captures). Once queued it is the photo's panel instead: its state, then what
Claude read, described and drew. Below the text are only the files it doesn't embed (PDFs, or
photos of pages made before this). Images on lines of their own (one or several in a row) become
figures; one in a link, heading, list or quote, or beside text, stays a plain image, and its file
is listed below the text as well. A page's download (and `scrap export`) points the text's images
and links at the files beside it (never inside code) and doesn't list a shown image again. Share
leaves out lines that only embed images. The figure code is a lazy chunk, outside the app shell.

## Excalidraw

The PWA embeds the Excalidraw React component, in a lazy chunk, to view and edit a photo's
drawing. On the page the drawing sits beside the photo when there is room (a Photo / Drawing
switch on a phone); tapping it opens a full-screen viewer where view and edit are one Excalidraw
scene.

Drawings are versioned. A human edit saves a new current version (producer `human`, author
recorded) and carries the `base_version` it was edited from, so a stale save gets `409`. The
history lists every version and Restore makes an old one current again as a copy. Reprocess never
replaces a human version unless the user confirms (*Replace mine* or *Keep mine*); otherwise the
new drawing is kept in the history only.

## MCP tools

Served at `/mcp` by the official MCP SDK inside the FastAPI app (Streamable HTTP, stateless,
JSON replies), so a session adds it with one `claude mcp add --transport http` line and nothing
local, and it works the same behind the cluster's ingress. A stdio `scrap mcp` command was the
alternative: it needs a shell where the database is (inside the container), which no client
session has. Tools and limits: [](../reference/mcp.md).

- `search`, `read`, `recent`, `todos`, `tags`: thin wrappers over the store; `search` takes the
  search box's syntax. Results carry each page's PWA URL (`$SCRAP_PUBLIC_URL/p/<slug>`) and its
  images as URLs, so Claude links there instead of trying to show them. Page text is returned in
  JSON fields, as data. `read` also returns `by_model`: Claude's own summary, the tags it added and
  the pages it found related, labelled as written by a model.
- `edit_meta` and `rename_tag` change the kind and tags of any page, `revisions` lists a page's
  text and metadata revisions (the way to find an id), and `revert` undoes a metadata change (or a
  whole bulk change by its batch id): metadata only, made safe by revisions
  ([](decisions/0019-kinds-and-tags-editable-with-revisions.md)).
- `edit_page` changes the text of any page narrowly (one passage found exactly once, or the whole
  body given its current `rev`) and `revert_text` restores an earlier text, each as a new
  `page_rev` revision by author `claude`, which `is:claude-edited` finds
  ([](decisions/0022-page-text-editable-over-mcp-with-revisions.md)). `SCRAP_MCP_CONTENT_EDIT=0`
  turns both off. No tool deletes a page or overwrites a body unconditionally.
- `write` only adds: a new page, or a section appended to a page written over MCP (`append_to`).
  It can also set `status`, `due`, `priority` and `snoozed_until`. Provenance is the capture's
  source `mcp` (which clients of the HTTP API cannot send), author `claude`, and a free-text
  `fields.origin`; no migration was needed. The PWA shows a badge; `is:claude` filters. A client
  key is hashed into the capture id, the store's existing retry key. The tools take the short kind
  names `note`, `todo`, `read`, `board` and `doc`, and results always show the stored ones
  (`read` is `consume`, `board` is `whiteboard`, `doc` is `document`).
- Limits per write: a body of at most 200 000 bytes, 20 tags, a 200-character title, and 200 pages
  in a bulk `edit_meta`; a request body of at most 2 MB.
- `/mcp` checks the `Host` and `Origin` of every request (DNS rebinding protection): loopback and
  the hosts of `SCRAP_PUBLIC_URL` (comma separated; the first also makes the page links) are
  allowed. Set it to the Tailscale Serve address or an MCP client gets `421` or `403`. The status
  codes are in [](../reference/api.md).
- Deferred: `ingest` (a URL or text as a capture), a `context` tool for a photo's stored model
  run, deleting and ticking a todo (PWA actions).

## Security posture

- **One gate in front.** On a server, Tailscale Serve is the only way in and Funnel stays off; the
  tailnet policy grants the scrap device to the owner's own devices only, and tagged servers (for
  example any internet-facing box) must not be able to reach it. On Kubernetes the gate is
  Cloudflare Access, with a service token and `SCRAP_MCP_TOKEN` on `/mcp`
  ([ADR 0023](decisions/0023-bearer-token-on-mcp-and-an-identity-header-setting.md)).
- **What listens where.** A single-server install listens by default only on a Unix socket (mode
  600, in a folder closed to other users; `scrap serve --uds`), with Serve proxying to it, so
  only that user, root and Serve can reach it and set the identity headers. Loopback TCP
  (`SCRAP_LISTEN=tcp`, published on `127.0.0.1:$SCRAP_PORT`, default 8790) is an opt-in there, and
  what an env file from before the socket keeps; any local process can reach it and send any
  `Tailscale-User-Login`. Running `scrap serve` yourself listens on `127.0.0.1:8000` unless told
  otherwise, with the same caveat. Under Helm the Service is in-cluster (a ClusterIP), with an
  optional NetworkPolicy. The caveats of
  [](decisions/0018-unix-socket-for-single-server-installs.md) stand: root (and so `sudo`) and
  anything running as the scrap user can still open the socket and forge the header, so run scrap
  as its own user.
- **Identity is attribution, not the gate.** The ACL is the gate. `author` is the
  `Tailscale-User-Login` header. Tagged devices send none, so their requests are recorded with the
  fallback author `tagged`. Whether the Tailscale Kubernetes operator's ingress passes the header
  is expected from its source but not yet verified
  ([](../how-to/deploy-kubernetes.md)).
- **What it holds.** Its database, files and Claude API key. No cluster or git credentials
  (service-account token automount off in the chart), no shell tools.
- **Prompt injection.** Ingested content is untrusted data. Claude is called with a fixed prompt, no
  tools and a JSON schema, so there is nothing to call, no file to read and no shell. The output is
  checked against the schema and sanitised, and the user's text is never edited. The worst outcome
  is a wrong page, a wrong provisional title or wrong tags and kind, which `page_rev` and
  `page_meta_rev` can undo. URL fetching refuses private and tailnet addresses, re-checked after
  DNS resolution and after every redirect, and connects to the address it checked (`fetch.py`).
- **Reading is not acting.** Sessions holding cluster or other powerful credentials should not
  mount the scrap MCP server, since pages may hold injected text.

## The PWA

Vanilla TypeScript built by Vite into the Python package (`scrap/static`); React and Excalidraw
(the drawing viewer) and Mermaid load only when needed. The screens are `/` (capture), `/search`
(`/recent` redirects there), `/tags`, `/todos` and `/p/<slug>`. The service worker precaches the
app shell and the lazy chunks that work offline (the page view, the composer and editors, the Markdown renderer,
the sharing code, and the search screen's Filters and recent searches), and also catches the share
target's POST, queueing it in IndexedDB like any capture; the server's `POST /share` is a fallback
if it does not. See
[](../how-to/use-the-pwa.md).

## Unused files (`scrap gc`)

A page shows its images by embedding them in its text (`![](/api/blobs/<sha>/preview?size=2048)`;
a photo capture writes one per photo), and only there: a photo whose embed is deleted from the
text is no longer shown or used as the page's thumbnail. A photo of a page made before photos were
embedded, which no revision ever embedded, is still listed below the text. The editor warns on
Save when an embed of a stored file goes, naming the file and how many other pages still show it.

`scrap gc` deletes the files nothing uses, and is a dry run unless given `--delete` (`--dry-run`
overrides it): a file is in use while any page's text (the trash's too) mentions its address, or a
capture, a `derived` row, an ingest `job` or a `model_run` (its photo or `sent_sha256`) refers to
it. Captures are never purged, so a photo's own file, and its Claude results, stay after its embed
is deleted and after its page is trashed; what gc deletes today is files nobody recorded (failed
or abandoned uploads), leftover upload temporaries and files only a page's text used. Only each
page's current text counts: old revisions are not references, so a file only an old revision
embedded can go (harmless while captures keep their photos; it would matter if Save ever unlinked
a photo from its capture). Page text is read for references by one function, `store.body_refs`: any
mention of a file's address counts, even in code or a full URL. It deliberately does not use the
Markdown parser, as gc deletes whatever it misses. A run reads every reference in one transaction
(and refuses if it cannot), skips files younger than the grace period (`--grace-hours`, 24 by
default), then rereads the references inside a write transaction before deleting; each file is
renamed aside and its age checked again, because `Store.put_blob` touches a file it finds already
stored, so an upload of the same bytes in flight keeps it. Its previews go with it. A run that
stops between the rename and the delete or relink leaves the file aside; the next run puts back
every such file whose name is free before it looks at anything. On a single server a nightly timer
runs it, after the backup, and only deletes if there was a backup in the last 26 hours. See
{ref}`the deploy guide <scrap-gc>`.

## Import

`scrap import` brings in a Thoth vault ([how-to](../how-to/import-a-vault.md)) through `Store`,
so revisions and the search index stay consistent. Each page keeps the vault's dates (its
`created_at`, `updated_at` and revision 1), kind (fixed), fields and tags; its capture has source
`import`, the vault file as its text (which also keeps ingest from retitling it) and the page's
images, PDFs in a second `file` capture. The capture id is made from the page's path, so a second
run skips pages already imported. Links between pages become `[[slug|label]]`, which the PWA
renders as links to `/p/<slug>`; images are embedded as `![](/api/blobs/<sha>/preview?size=2048)`,
as a photo capture's are. Dates alone become noon UTC. A rerun never updates a page already
imported.

The search index holds the labels of links and images, not their addresses (for every page, not
only imported ones), so `/api/blobs/...` and URLs in Markdown links (`<...>` addresses too) are
not words to find: a hand-written link is found by its text, not its domain, by choice.

### Markdown

Page text is Markdown ([issue 71](https://github.com/gilesknap/scrap/issues/71)), parsed by a
library on both sides with the same grammar: CommonMark plus GitHub's tables, strikethrough and
footnotes, `[[slug|label]]` page links, raw HTML as text and a line break kept as one. The PWA
renders it with markdown-it (task lists, bare `https://` links and heading ids too) in
`render.ts`, a lazy chunk the service worker keeps for offline use, so the app shell stays within
its 16 kB gzipped budget; the page view loads it while it fetches the page, and without it (offline before
it was kept) shows the text as typed. A post-parse pass allows only http(s), mailto, page and
in-page links (opened with `rel=noopener`), and only this server's own images, each marked with its
`data-sha` for `figure.ts`. A ` ```mermaid ` block is drawn by Mermaid, a separate chunk loaded only
for a page that has one (not kept offline: it is big), with `securityLevel: 'strict'`; it is
bundled, not loaded from a CDN, so the CSP needs no change. That CSP (a `<meta>` in `index.html`)
sets `default-src 'self'` and `script-src 'self' 'wasm-unsafe-eval'`: the theme is applied before first paint by
`/theme-init.js`, not an inline script. `style-src` keeps `'unsafe-inline'` because Mermaid and
Excalidraw write style attributes and elements. `'wasm-unsafe-eval'` is there because the bundle
compiles WebAssembly (pica and image-blob-reduce resize an image added to a drawing; Excalidraw's
font subsetting is an Emscripten module), which `script-src 'self'` alone blocks; it allows
WebAssembly only, not `eval()`, `new Function()` or inline scripts, and `tests/csp.test.ts` keeps
`'unsafe-eval'` and `'unsafe-inline'` out of `script-src`. The font subsetting module also builds
functions with `Function()`, which only `'unsafe-eval'` would allow; that is refused, so Excalidraw
logs "Skipped glyph subsetting" and an SVG export embeds the whole font it uses instead of
the glyphs drawn (about 40 kB against 13 kB for a three-box sketch); PNG exports, the stored
drawing, which holds no fonts, and what shows on screen are unchanged
([issue 105](https://github.com/gilesknap/scrap/issues/105)).

The server parses with markdown-it-py (`scrap/markdown.py`, with mdit-py-plugins for footnotes):
the search index holds plain text from the parse (link and image text, not addresses; a page
link's label; code as typed; a table's cells; no markup), and the importer rewrites links,
images and wiki links found by the parse, mapped back to their place in the text, so code is
never rewritten and a link in a table cell escapes every pipe (a block whose lines can't be
mapped back keeps its links as typed, and the import plan says so). Tests keep both parsers linear
in the length of the text on hostile input (long runs of brackets, say). Migration 4 re-indexed
every page this way.

## Operating it

The commands and settings are in [](../reference/api.md); this is how they fit together.

- **Commands.** `scrap serve` (migrates, then serves), `backup DIR`, `restore DIR`, `export DIR`,
  `import DIR`, `gc`, `enrich` (`--backfill`, `--related`) and `ingest-once IMAGE`. Every command
  takes `--data-dir` (default `$SCRAP_DATA_DIR`, else `./data`).
- **Settings** are environment variables: `SCRAP_DATA_DIR`, `SCRAP_WEB_DIR`, `SCRAP_PUBLIC_URL`,
  `SCRAP_MAX_UPLOAD_MB` (50), `SCRAP_REVISION_WINDOW` (300), `SCRAP_INGEST` (off), `SCRAP_ENRICH`
  (on, but only with ingest on), `ANTHROPIC_API_KEY`, `SCRAP_VISION_MODEL`, `SCRAP_TEXT_MODEL`,
  `SCRAP_TEXT_EFFORT`, `SCRAP_ENRICH_DEBOUNCE` (60), `SCRAP_BUDGET_DAY_USD` (3) and
  `SCRAP_NOTIFY_URL`. "Today" in `due:today` is the server's local day, so set `TZ`.
- **Backup.** `scrap backup` takes an online SQLite backup plus a copy of `files/`, safe while
  serving. `restore` checks the copy's integrity and that its schema is not newer than the code,
  works from read-only media (it opens a copy made in the data folder), and refuses a non-empty
  data folder unless given `--force`. The preview cache is never backed up.
- **Timers.** On a single server `install.sh` sets up three systemd user timers: a nightly backup
  (keeping the newest `SCRAP_BACKUP_KEEP` runs), `scrap gc` after it, and the related-pages pass
  `scrap enrich --related`. The Helm chart has only the backup CronJob. A health check is `GET
  /healthz`, which also reports the upload limit.
- **Cost.** Every call records its cost from the usage and a price table, and the daily budget
  and the Console spend limit cap the total. `scrap ingest-once IMAGE` prints what one photo costs
  ([](ingest.md)).

## Deferred

- Voice memos (needs a transcriber).
- Background Sync for the upload queue.
- Filing captures into existing pages, and automatic cross-linking.
- A `namespace` column for read scoping by less trusted surfaces.
- Embeddings and hybrid search, if exact words and filters stop being enough
  ([](decisions/0008-search-fts5-only-for-now.md)).
- Purging trashed pages and their captures (there is no empty-trash command).
- A page listing dead jobs. The queue's state is shown on each page and in `GET /api/ingest`, with
  *Resume* and per-photo *Retry*, but there is no overview.
- Chat and refine on a photo's stored model run.

Larger ideas:

- **Work browser route.** A Cloudflare tunnel plus Access (passkey-capable IdP, short sessions) in
  front of the PWA only; the service verifies the Access JWT itself. Cloudflare sees plaintext.
- **Work sandbox.** Userspace Tailscale (no root, no TUN), an ephemeral tagged key, an ACL to the
  MCP port only; scoped `search` and `read`, inbox-only writes.
- **PKM session pod.** A remote Claude Code session in the cluster with only the scrap MCP server.
- **Separate ingest worker.** The same image with another command, if LLM work needs isolating.

## Open questions

- **Headless terms.** Partly settled: `claude setup-token` is Claude Code's own route for
  headless use, and the seat backend uses it ([ADR 0021](decisions/0021-ingest-on-a-claude-seat-through-claude-p.md)).
  Whether an organisation allows a seat to run unattended is its own policy: users check with
  its Claude admin.
- **Audio transcription** (for voice memos). Local faster-whisper or a hosted API.
- **Postgres and pgvector**, only if SQLite is outgrown.
- **Cloudflare route auth.** Which identity provider and session length; capture or view only.
- **Work sandbox scope.** Namespaced reads or full read; whether work material gets a namespace.
- **Tailscale Kubernetes operator.** Whether its ingress passes the identity headers through; its
  source says it does, but this is not yet verified ([](../how-to/deploy-kubernetes.md)).
