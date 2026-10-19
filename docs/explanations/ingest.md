# Claude ingest (M2)

Status: design for milestone 2. It builds on the M1 code on `main` (schema `0001_init.sql`,
`store.py`, `app.py`) and the PWA, and supersedes parts of [the design](design.md) listed there.

M2 sends each photo to Claude once and gets back its text, a description, a kind, a title, tags
and an Excalidraw drawing. The photo stays the original; everything Claude returns is a derived
version that can be regenerated, edited by hand or discussed later. Every call is stored with its
messages, so a later conversation (M4, in the PWA) or a Claude Code session over MCP (M3) starts
from the same context the model had.

## Decisions in brief

- **Worker**: one thread inside the existing service, one job at a time.
- **Backend**: the Messages API with a key from the environment, no tools. `claude -p` is the
  fallback behind a switch.
- **One combined vision call per photo**, on a downscaled JPEG preview, with structured output
  that is validated and sanitised in code.
- **Only photos are ingested in M2.** Notes and links keep their M1 titles; capture buttons set
  the kind.
- **Results are versions**: model or human, newest current, older kept.
- **A model outage pauses the whole queue** once, with one notification, instead of burning
  per-job attempts.

## Worker

The worker is a daemon thread started by the FastAPI lifespan. It is not an asyncio task,
because `Store` is synchronous and the Claude call blocks. It is not a separate process either:
SQLite has one writer at a time, the service already runs as a single replica (on k8s and on a
single server alike), and a second process would mean a second deployment unit for no gain yet.
`SCRAP_INGEST=off` (the default until the spend controls land) leaves the thread unstarted.
Because the claim is one atomic SQL statement, a later `scrap worker` command can run the same
loop in its own container with no schema change.

**Jobs.** Saving a photo capture enqueues one `ingest` job per photo (`source_sha256` is that
photo), in the capture's own transaction. A multi-photo capture therefore fails and retries per
photo. The partial unique index `job_one_active` allows one queued or running job per step, so a
second *Reprocess* is a no-op.

**Claim.** The thread wakes on enqueue (a `threading.Event`) or every 30 s and claims the oldest
ready job whose page is not in the trash, unless the queue is paused:

```sql
UPDATE job SET state = 'running', attempts = attempts + 1, updated_at = :now
WHERE id = (
    SELECT j.id FROM job j
    LEFT JOIN capture c ON c.id = j.capture_id
    JOIN page p ON p.id = coalesce(j.page_id, c.page_id)
    WHERE j.state = 'queued' AND j.run_after <= :now AND p.deleted_at IS NULL
    ORDER BY j.run_after, j.id LIMIT 1)
  AND NOT EXISTS (SELECT 1 FROM queue_state WHERE paused_until > :now)
RETURNING id, kind, capture_id, source_sha256, attempts
```

Concurrency is 1. That is enough for one person (20 to 55 s per board) and stays far below any
rate limit. **Steps**:

1. Insert a `model_run` row (status `running`).
2. Call Claude holding no lock. The timeout is 240 s per call.
3. In one `BEGIN IMMEDIATE`: re-read the job (a purge may have removed it, which counts as
   finished), finish the run, insert the derived versions, apply the page rules below, and mark
   the job `done`.

At start-up, runs left `running` become `error`/`internal`, and running jobs go back to
`queued`.

**Retries.** A content failure (see Spend and outage control below) sets
`run_after = now + 2^attempts` minutes, and the third failure marks the job `dead`. An outage
refunds the attempt and pauses the queue instead.

**What the PWA shows** per capture, from its jobs: *queued*, *processing*, *done* or *failed*
(any `dead` job, with `last_error`), plus *paused* while the queue is paused. A page has
**Reprocess** (per photo); a failed one has **Retry**. A *Failed* view lists dead jobs, and a
banner shows a paused queue with its reason and a **Resume** button.

## The Claude call

One small function, `complete(model, system, messages, schema) -> Result`, returns the validated
JSON, the raw content blocks, the usage and the served model.

- **Backend `api`** (default): the official `anthropic` SDK, with the key in
  `ANTHROPIC_API_KEY`, read from the service user's own mode-600 env file. Structured output
  goes through `output_config.format` (JSON schema), and the call has no `tools`. The API key
  can do nothing but spend inference credit, and the Console spend cap bounds that.
- **Backend `cli`** (`SCRAP_LLM_BACKEND=cli`): `claude -p --json-schema ...` on a subscription
  login, with only the Read tool, in a throwaway directory holding the one preview. These are the
  flags the whiteboard experiment used. Before relying on it unattended, confirm that the current
  terms permit unattended headless use. It records usage from the CLI's JSON output.

**Image.** Claude is never sent the original. The worker sends the PWA's cached JPEG preview:
EXIF orientation applied, HEIC converted (Pillow with pillow-heif), longest edge 2048 px, quality
85. That is far below the API's per-image size limit (5 MB at the time of writing) and about 4k
image tokens. The preview is regenerable cache; the run records the original's sha256, the
preview's size and its sha256. Drawing coordinates are in preview pixels.

**One combined call** returns `kind`, `title`, `tags`, `description`, `text` (one item per line,
`(?)` after uncertain readings) and `elements` (Excalidraw skeletons). The prompt grows from the
experiment's `skeleton_v3`. It adds title and tags, and asks for an empty `elements` list unless
`kind` is `whiteboard` or `diagram`, so a holiday photo costs no drawing tokens.

**Prompts** live in `src/scrap/prompts/` (for example `photo.md`, plus the schema in Python).
`prompt_version` is `<name>@<first 12 hex digits of sha256(prompt + schema)>`, so an edit can't
forget to bump it.

**Models and effort.** These are set by environment variables and recorded per run:

- `SCRAP_VISION_MODEL` defaults to Opus (`claude-opus-5-5`): it read handwriting best.
- `SCRAP_VISION_FALLBACK`, when set, makes the primary model a cheaper first pass. Point the
  primary at Sonnet (`claude-sonnet-5-5`) and the fallback at Opus. If the text contains 3 or more
  `(?)`, the same job runs again on the fallback, and both runs are kept.
- Thinking cannot be turned off on the current Opus, so `effort` is set explicitly (`medium` to
  start) and tuned on the experiment's boards.
- `max_tokens` is 16000 (the densest board used about 6.4k output tokens).
- A text-only call, for later, uses Haiku.

**Notes and links (decision: none in M2).** Capture buttons already choose the kind, and the
first line or the URL is a usable title. Summarising a link without fetching it invites
invention, and fetching needs the private-address rules in the design's security section. Both
wait. `complete()` takes calls without images, so adding them later is configuration, not
schema. File captures (PDFs) wait too.

## Stored context for later discussion

A `model_run` row is one call:

- **Identity**: capture, photo, job, `purpose` (`ingest`, `refine`, `discuss`) and `parent_id`
  (the turn it continues).
- **Settings**: backend, requested and served model, `prompt_version`.
- **`request`**: the system prompt text, the messages and the parameters. Each image block is a
  reference such as `{"type": "image", "blob": <sha256>, "preview": {...}}`, never base64.
- **`response`**: the content blocks exactly as returned, thinking blocks and their signatures
  included, plus `stop_reason`.
- **Results**: the validated `output`, the `usage`, `cost_microusd`, `status` and
  `error_class`, and timestamps.

A run is about 10 to 50 KB (the prompt text is stored per run, so a replay never depends on
today's prompt file). Ten boards a day comes to well under 200 MB a year. **Retention.** Runs
are kept. A run that backs a derived version cannot be deleted (a foreign key with no action). A
later `scrap prune-runs` may drop failed or unreferenced runs older than 90 days. Runs live in
the database, so the existing backup covers them.

**Discuss and refine (M4).** The API is stateless, so a conversation is a stored message list.
Continuing run *R* sends:

- *R*'s `system`;
- *R*'s messages, with the images rehydrated from the preview cache;
- *R*'s `response` content as the assistant turn, verbatim;
- one new user turn: the request, plus the current drawing when a human version is newer than
  *R*'s.

The history is append-only, never edited, which current models require for thinking blocks to
stay valid. Use the same model as *R*; other models ignore its thinking blocks. The new run gets
`parent_id = R`. A refine returns a new skeleton, which becomes a new model version. Each turn
re-sends the image tokens. Prompt caching helps only within an active chat (5-minute TTL), so a
turn costs roughly one ingest's input plus the history.

**MCP (M3).** `read` returns, per photo:

- the preview's PWA URL, `image_kind`, the OCR text and the description;
- the current drawing's version, producer and element count;
- `context_run`, the run id.

With `include_drawing`, `read` also returns the drawing's JSON. A `context` tool returns that
run's prompt, output, model and usage, with the preview as MCP image content. A fresh Claude
Code session then knows what the ingest model saw and said; continuing the *same* API
conversation is the PWA's job (M4).

## Derived results and versions

M1 has no `derived` table; 0002 creates it with versions, replacing the design's "regenerating
replaces it". Each `(capture, photo, kind)` has at most one **current** row (`superseded_at IS
NULL`, enforced by a partial unique index). A trigger supersedes the previous row when a current
one is inserted. Rows are immutable apart from being superseded once. **Restore** inserts a copy
of an old version as a new current one, so history only grows.

- **Kinds**: `ocr` and `description` (text, indexed; the description's `data` holds
  `image_kind`), `excalidraw` (`data` holds `{"format": "skeleton" | "scene", "width",
  "height", "elements"}`, JSON in the row rather than a blob, because it is small and versioned
  with the rest), and `summary` and `fetched` for later.
- **Producer** is the model id, or `human` with `author` set. `run_id` links a model version
  to its call.
- **The human wins.** A reprocess never replaces a human drawing on its own: the new model
  drawing is inserted already superseded (visible in History), unless the request said
  `replace_human` after the PWA asked. Text kinds simply get a new version.

**Page fields** follow the M1 "user wins" rules and come only from the photo with `ord = 0`:

- **Title.** Replaced only while the page is still at rev 1 and its title is the device date
  (the capture had no text). This writes rev 2 with the model id as author. The slug follows,
  since nothing can link to it yet (there are no `[[links]]` in M1).
- **Tags.** Written on the first successful ingest of a page that has none (0002 adds `tag`).
- **Kind.** Set only while `kind_fixed = 0` and the kind is still `note`: `whiteboard` and
  `diagram` become `whiteboard`, `document` becomes `document`, and anything else leaves it. A
  capture button has already fixed the kind. The mapping is one table in code, so whatever issue
  #11 decides about kinds needs no schema change (`image_kind` is kept either way).

**Search.** A trigger indexes a current version's `text` as a chunk with `derived_id` set, and
superseding removes that chunk. That covers OCR, the description and a human drawing's labels; a
model drawing has `text` NULL, since its words are the OCR. Two M1 code changes come with it:

- `Store._index` must delete only `derived_id IS NULL` chunks, or a page edit wipes the derived
  ones;
- search must group hits by page.

A trashed page's derived hits are hidden by the existing `deleted_at` filter.

## Excalidraw in the PWA

- **Storage.** Model drawings are stored as the validated skeleton; the browser expands them with
  `convertToExcalidrawElements`.
- **Loading.** `@excalidraw/excalidraw` (with React) is loaded by a Vite dynamic `import()` only
  when a drawing is opened. The base app stays vanilla TypeScript and about 8 kB gzipped; React
  lives only in that chunk.
- **Fonts.** `EXCALIDRAW_ASSET_PATH` points at fonts served by scrap, because the default
  fetches them from a public CDN. The service worker caches the chunk on first use.
- **Converter workarounds** from the experiment, both kept:
  - an arrow bound to a free `text` element carries that text's own `x`/`y` in `start`/`end`
    (Excalidraw 0.18 otherwise moves the text);
  - the scene is converted again once `document.fonts.ready` resolves, so labels are measured
    with the right font.
- **Viewing and editing.** The drawing opens in view mode, with the photo beside it on wide
  screens or as tabs on a phone. **Edit** switches to edit mode. **Save** sends the full element
  JSON with the base version (409 if stale, as for page edits); the server sanitises it and
  stores a `scene` version by `human` with its text labels as `text`. **History** lists versions
  with **Restore**.
- **Export.** `.excalidraw` (`serializeAsJSON`), PNG (`exportToBlob`) and SVG (`exportToSvg`),
  all in the browser.

**Validation before anything reaches the renderer.** Server side, for both formats:

- element types allowlisted: `rectangle`, `ellipse`, `diamond`, `text`, `arrow`, `line` (plus
  `freedraw` in human scenes); no `image`, `embeddable`, `iframe` or `frame`;
- known keys only, and no `link`, `customData` or `fileId`;
- ids up to 32 characters of `[A-Za-z0-9_-]`, colours `#rrggbb`;
- finite numbers, positions within a quarter of the image beyond its edges, font size 4 to 200,
  at most 200 points per line, text up to 2000 characters, at most 1000 elements.

Bad elements are dropped, not fatal. A run fails only if no text and no description remain, so a
stray coordinate never costs a paid retry. Human scenes may carry an http(s) `link`; nothing else
does.

**Prompt injection.** The image is data. The call has no tools and no network access. Its output
is schema-checked and sanitised, nothing in it is fetched or executed, and it can only change its
own page's derived versions, title, tags and kind. Each of those can be undone through versions
or `page_rev`.

## Spend and outage control

**Cost.** Each run records its `usage`, and a price table in code turns that into
`cost_microusd`. The experiment measured $0.10 to $0.21 per board through `claude -p`, including
the CLI's own large system prompt. The direct API should cost less: mostly output tokens (about
1 to 6k, plus thinking). PR 1 measures it. Spend is a sum over `model_run` by `started_at`:

- **Soft limits.** `SCRAP_BUDGET_DAY_USD` (default 3) and `SCRAP_BUDGET_MONTH_USD` (default 40,
  under the Console cap) pause the queue (reason `budget`) until the next UTC day or month.
- **Hard limit.** The Console's workspace spend cap.

**Errors.**

| Class | What | Effect |
| --- | --- | --- |
| content | 400 (other than credit), 413, refusal, `max_tokens`, nothing valid left, an image that will not decode | counts against the job; dead after 3 |
| auth / config | 401, 403, 404 (unknown model) | pause until *Resume* |
| credit | 402, or a 400 that says the credit balance is too low | pause until *Resume* |
| rate_limit | 429 | pause until `retry-after` |
| outage | 500, 529, connection error, timeout (after the SDK's own 2 retries) | pause 1, 2, 4 ... 60 min (`failures`) |

A pause refunds the job's attempt, so no job dies during an outage. The **first** pause of an
episode sends one notification and sets `notified_at`. A success clears the pause, `failures`
and `notified_at`.

`SCRAP_NOTIFY_URL` is off when unset. The notification is a POST with a text body and a `Title`
header, which an ntfy topic URL or any simple webhook accepts. The PWA banner, the *Failed* list,
**Resume** and **Reprocess** cover the rest.

## Migration 0002 (sketch)

Applied by the M1 runner after `0001_init.sql`. Every connection already sets `foreign_keys` and
`busy_timeout`. Hard deletes cascade (a later purge); soft delete is handled in the claim query
and in search.

```sql
CREATE TABLE tag (
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL CHECK (tag = lower(tag) AND length(tag) BETWEEN 1 AND 64),
    PRIMARY KEY (page_id, tag)
);
CREATE INDEX tag_by_name ON tag(tag);

CREATE TABLE job (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('ingest', 'refine', 'embed')),
    capture_id    TEXT REFERENCES capture(id) ON DELETE CASCADE,
    source_sha256 TEXT NOT NULL DEFAULT '',    -- the photo; '' for the capture's text or url
    page_id       TEXT REFERENCES page(id) ON DELETE CASCADE,
    state         TEXT NOT NULL DEFAULT 'queued'
                    CHECK (state IN ('queued', 'running', 'done', 'dead')),
    attempts      INTEGER NOT NULL DEFAULT 0,  -- claims, less those refunded for outages
    options       TEXT NOT NULL DEFAULT '{}' CHECK (json_type(options) = 'object'),
    run_after     TEXT NOT NULL,
    error_class   TEXT CHECK (error_class IN ('content', 'outage', 'budget', 'internal')),
    last_error    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    CHECK (capture_id IS NOT NULL OR page_id IS NOT NULL)
);
CREATE INDEX job_ready ON job(state, run_after);
CREATE INDEX job_by_capture ON job(capture_id);
-- At most one queued or running job per step: Reprocess twice is a no-op.
CREATE UNIQUE INDEX job_one_active ON job(kind, capture_id, source_sha256)
    WHERE state IN ('queued', 'running');

-- One row. A pause stops every claim until paused_until (far future: until Resume).
CREATE TABLE queue_state (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    paused_until  TEXT,                        -- NULL: running
    reason        TEXT CHECK (reason IN
                    ('auth', 'credit', 'rate_limit', 'outage', 'budget', 'config', 'manual')),
    detail        TEXT,
    failures      INTEGER NOT NULL DEFAULT 0,  -- consecutive outage errors: the backoff exponent
    notified_at   TEXT,                        -- this pause has been announced
    updated_at    TEXT NOT NULL
);
INSERT INTO queue_state (id, updated_at) VALUES (1, '1970-01-01T00:00:00.000Z');

-- Every model call, kept so a conversation can resume from it. Images are referenced by
-- blob sha256, never embedded.
CREATE TABLE model_run (
    id             INTEGER PRIMARY KEY,
    capture_id     TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    source_sha256  TEXT NOT NULL DEFAULT '',
    job_id         INTEGER REFERENCES job(id) ON DELETE SET NULL,
    parent_id      INTEGER REFERENCES model_run(id),  -- the turn this one continues (M4)
    purpose        TEXT NOT NULL CHECK (purpose IN ('ingest', 'refine', 'discuss')),
    backend        TEXT NOT NULL CHECK (backend IN ('api', 'cli')),
    model          TEXT NOT NULL,              -- requested
    served_model   TEXT,                       -- as reported by the response
    prompt_version TEXT NOT NULL,              -- e.g. photo-v4@3f9c2a1b0d4e
    request        TEXT NOT NULL CHECK (json_valid(request)),
    response       TEXT CHECK (json_valid(response)),  -- content blocks as returned, stop_reason
    output         TEXT CHECK (json_valid(output)),    -- the validated result
    usage          TEXT CHECK (json_valid(usage)),
    cost_microusd  INTEGER NOT NULL DEFAULT 0,  -- estimated from usage and a price table
    status         TEXT NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'ok', 'invalid', 'refused', 'error')),
    error_class    TEXT CHECK (error_class IN ('content', 'outage', 'budget', 'internal')),
    error          TEXT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT
);
CREATE INDEX model_run_by_source ON model_run(capture_id, source_sha256);
CREATE INDEX model_run_by_started ON model_run(started_at);  -- spend per day and month

-- Results as versions: one current row (superseded_at IS NULL) per (capture, photo, kind),
-- older ones kept. Rows are never changed except to supersede them.
CREATE TABLE derived (
    id            INTEGER PRIMARY KEY,
    capture_id    TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    source_sha256 TEXT NOT NULL DEFAULT '',
    kind          TEXT NOT NULL CHECK (kind IN
                    ('ocr', 'description', 'summary', 'fetched', 'excalidraw')),
    version       INTEGER NOT NULL CHECK (version >= 1),
    producer      TEXT NOT NULL,               -- model id, or 'human'
    run_id        INTEGER REFERENCES model_run(id),  -- the call that made it; NULL if human
    author        TEXT,                        -- who saved a human version
    text          TEXT,                        -- indexed while current
    data          TEXT CHECK (json_valid(data)),  -- excalidraw: {"format": ..., "elements": ...}
    out_sha256    TEXT REFERENCES blob(sha256),
    superseded_at TEXT,                        -- NULL: the current version
    created_at    TEXT NOT NULL,
    UNIQUE (capture_id, source_sha256, kind, version)
);
CREATE UNIQUE INDEX derived_current ON derived(capture_id, source_sha256, kind)
    WHERE superseded_at IS NULL;
CREATE INDEX derived_by_run ON derived(run_id);

-- Inserting a current version supersedes the previous one. Insert with superseded_at set to
-- keep a version in history only (a model result that must not replace a human edit).
CREATE TRIGGER derived_supersede BEFORE INSERT ON derived
WHEN new.superseded_at IS NULL BEGIN
    UPDATE derived SET superseded_at = new.created_at
    WHERE capture_id = new.capture_id AND source_sha256 = new.source_sha256
      AND kind = new.kind AND superseded_at IS NULL;
END;
CREATE TRIGGER derived_immutable BEFORE UPDATE OF capture_id, source_sha256, kind, version,
    producer, run_id, author, text, data, out_sha256, created_at ON derived BEGIN
    SELECT RAISE(ABORT, 'derived versions are immutable: insert a new version');
END;
CREATE TRIGGER derived_once BEFORE UPDATE OF superseded_at ON derived
WHEN old.superseded_at IS NOT NULL BEGIN
    SELECT RAISE(ABORT, 'a superseded version stays superseded: insert a copy to restore it');
END;

-- Search: the current version's text is one chunk of its page (chunk_ai/chunk_ad keep FTS in
-- step). The page's own chunk is the one with derived_id NULL.
ALTER TABLE chunk ADD COLUMN derived_id INTEGER REFERENCES derived(id) ON DELETE CASCADE;
CREATE INDEX chunk_by_derived ON chunk(derived_id);

CREATE TRIGGER derived_index AFTER INSERT ON derived
WHEN new.superseded_at IS NULL AND coalesce(new.text, '') <> '' BEGIN
    INSERT INTO chunk (page_id, derived_id, ord, text)
    SELECT page_id, new.id, 0, new.text FROM capture WHERE id = new.capture_id;
END;
CREATE TRIGGER derived_unindex AFTER UPDATE OF superseded_at ON derived
WHEN new.superseded_at IS NOT NULL BEGIN
    DELETE FROM chunk WHERE derived_id = new.id;
END;
```

A new version is inserted with `version = (SELECT coalesce(max(version), 0) + 1 ...)` for its
key, inside a `BEGIN IMMEDIATE` transaction. The app strips control characters from `text`
before inserting, as M1 does for page chunks.

## Build order

1. **Worker, backend, runs.** Covers:
   - 0002, the worker thread (`SCRAP_INGEST=off` by default) and `complete()` (`api` backend);
   - the photo prompt, the sanitiser, and writing derived text, title, tags and kind;
   - the `_index` fix and search grouped by page;
   - capture state in the page and recent APIs, with a small status badge in the PWA;
   - `scrap export` writing OCR text and descriptions beside each page.
2. **Excalidraw view.** The lazy drawing chunk, the converter workarounds, view, edit and save
   as `human`, history and restore, and export. The Markdown export gains the current
   `.excalidraw` file.
3. **Spend and outage control.** Error classes, the global pause, budgets, `SCRAP_NOTIFY_URL`,
   the banner and *Resume*. Ingest is switched on for daily use only after this lands.
4. **Reprocess UI.** *Reprocess* (asking before it replaces a human drawing), the *Failed*
   list, the Sonnet-first option and the `cli` backend.

**Deferred:**

- MCP (M3), and chat or refine in the PWA (M4);
- URL fetching, and ingest of notes, links and PDFs;
- embeddings and vectors (the `embed` job kind is reserved);
- pruning runs;
- anything Notion-like.

## Risks and unknowns

- **Latency.** Opus took 11 to 55 s per board, so a capture shows *processing* for up to a
  minute.
- **Credits.** The promotional credits may expire or be monthly, and the cap is $50. A
  `credit` pause makes running out visible rather than silent.
- **Prompt drift.** Model updates change output. `prompt_version` and the served model per run
  make a regression traceable; keep the experiment's boards as a manual check set.
- **Excalidraw.** The package is large (around 1 MB or more minified, loaded lazily). Its API
  (`convertToExcalidrawElements`) is not guaranteed stable, and the 0.18 binding bug may change
  with an upgrade: pin the version.
- **Curves become polylines**, an accepted limit of skeletons.
- **HEIC** depends on pillow-heif wheels for aarch64 and x86_64. Check when the preview cache
  lands.
- **Refusals.** A refusal on an innocent whiteboard is possible; it is a content error, visible
  in *Failed*.
- **Replay** of stored thinking blocks depends on API rules about thinking blocks and model
  binding, which have changed before. If a replay is rejected, M4 can start a fresh call with
  the stored output as plain text.

## Open questions

- **Notes and links.** Leave them out of M2 entirely (this design), or add a cheap Haiku pass
  for tags and titles of shared links?
- **Budgets.** Are $3 a day and $40 a month right, and should the monthly figure track the
  credit balance rather than the cap?
- **Sonnet first.** Default to Opus only (this design), or Sonnet first to halve the cost of
  clean diagrams?
- **Reprocess and human drawings.** Should *Reprocess* ever replace a human drawing without
  asking, for example when the human version is only a few minutes old?
- **Kinds.** Issue #11: is `image_kind` (whiteboard, diagram, handwriting, screenshot,
  document, photo) the right vocabulary to map from?
