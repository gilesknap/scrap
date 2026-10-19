# Claude ingest (M2)

Status: design for milestone 2. It builds on the M1 code on `main` (`0001_init.sql`, `store.py`,
`app.py`) and the PWA, and supersedes parts of [the design](design.md) listed there.

M2 sends each photo to Claude once. One call returns the photo's text, a description, a kind, a
title, tags and an Excalidraw drawing. The original is kept; everything Claude returns is a
version that can be regenerated, edited or discussed. Every call is stored with its messages,
so a later chat in the PWA (M4) or a Claude Code session over MCP (M3) starts from what the model
saw and said.

**Settled for M2:**

- The Messages API only, on Opus.
- Photos only; notes and links are not ingested.
- Reprocess always asks before replacing a human drawing.
- The image kind is stored as given, so issue #11 does not block.
- A soft budget of $3 a day.

**Cut, with the reason:**

- A `claude -p` backend: a second code path that needs a Read tool. `complete()` is the seam if
  one is ever needed.
- A cheaper first-pass model: no cost data yet says it matters.
- A monthly budget: the Console spend limit already caps the month.

## Worker

One daemon thread, started by the FastAPI lifespan:

- not an asyncio task, because `Store` is synchronous and the call blocks;
- not a second process, because SQLite has one writer and the service runs as one replica.

`SCRAP_INGEST=off`, the default until spend control lands, leaves it unstarted. The capture
transaction enqueues one job per distinct photo:

```sql
INSERT INTO job (kind, capture_id, source_sha256, run_after, created_at, updated_at)
SELECT 'ingest', capture_id, sha256, :now, :now, :now FROM capture_blob
WHERE capture_id = :capture
ON CONFLICT DO NOTHING
```

`job_one_active` allows one queued or running job per photo, so a photo sent twice in a
capture, or *Reprocess* pressed twice, adds nothing. The thread wakes on enqueue or every 30 s.
It claims the oldest ready job whose page is not in the trash, unless the queue is paused:

```sql
UPDATE job SET state = 'running', attempts = attempts + 1, updated_at = :now
WHERE id = (
    SELECT j.id FROM job j
    JOIN capture c ON c.id = j.capture_id
    JOIN page p ON p.id = c.page_id
    WHERE j.state = 'queued' AND j.run_after <= :now AND p.deleted_at IS NULL
    ORDER BY j.run_after, j.id LIMIT 1)
  AND NOT EXISTS (SELECT 1 FROM queue_state WHERE paused_until > :now)
RETURNING id, capture_id, source_sha256, attempts, failures
```

One job runs at a time (11 to 55 s per board).

1. Insert a `model_run` row.
2. Call Claude holding no lock, with a 240 s timeout.
3. In one `BEGIN IMMEDIATE`:
   - re-read the job (a purge counts as done);
   - finish the run and write the versions and page fields;
   - mark the job `done`, or apply the error rules below.

Jobs `running` for over twice the timeout are requeued. In the PWA, each capture shows
*queued*, *processing*, *done*, *failed* (with its reason and **Retry**) or *paused*. A page has
**Reprocess** per photo, and a banner shows a paused queue with **Resume**.

## The Claude call

`complete(model, system, messages, schema)` returns:

- the sanitised JSON;
- the raw content blocks;
- the usage;
- the served model.

**Setup.**

- The call uses the `anthropic` SDK, with `ANTHROPIC_API_KEY` from the service user's mode-600
  env file.
- It has no `tools`, and SDK debug logging stays off, since that logs request bodies.
- The model is `SCRAP_VISION_MODEL`, default `claude-opus-5-5`, which read handwriting best in
  the experiment.
- Its thinking cannot be disabled, so `effort` is set explicitly (`medium` to start) and
  recorded. `max_tokens` is 16000.

**Image.** Claude never gets the original, but a JPEG made from it (EXIF orientation applied,
HEIC converted, quality 85). It is scaled to the largest size with a long edge of at most
2048 px and ⌈w/28⌉·⌈h/28⌉ ≤ 4784 image tokens, the high-resolution cap:

- a 4:3 photo is sent as 2048×1536 (4070 tokens);
- a square one as 1932×1932.

The API therefore never rescales it, and drawing coordinates are in sent pixels. The run stores
`image_width`, `image_height` and the JPEG's sha256, and the PWA scales the drawing to the
displayed photo. The per-image limit (10 MB) is far away.

**Output.** One call returns:

- `kind`: whiteboard, diagram, handwriting, screenshot, document, photo or other;
- `title` and `tags`;
- `description`;
- `text`: one item per line, with `(?)` after uncertain readings;
- `elements`: empty unless the kind is whiteboard or diagram.

The prompt grows from the experiment's `skeleton_v3`. Prompts live in `src/scrap/prompts/`.
`prompt_version` is `<name>@<12 hex digits of sha256(prompt + schema)>`, so an edit always gets
a new version.

**Schema.** It uses the subset that Anthropic's structured outputs documentation lists as
accepted:

- `additionalProperties: false` on every object;
- no numeric or string bounds;
- `minItems` of 0 or 1 only;
- at most 24 optional and 16 union-typed properties.

The experiment's schema broke it with `[x, y]` tuples and about 16 nested optional fields. So
an element is one flat object:

- `type`, `x` and `y` are required;
- 12 optional fields, none a union: `id`, `width`, `height`, `text`, `fontSize`, `label`,
  `labelFontSize`, `points` (flat `[dx0, dy0, dx1, dy1, ...]`), `start`, `end`, `strokeColor`
  and `startArrowhead`.

Code turns these into Excalidraw skeletons, and the sanitiser enforces the bounds. Nothing yet
shows that the API accepts this schema together with adaptive thinking on Opus; the experiment
used `claude -p`, which proves nothing here. PR 1 makes one real call first.

## Stored context for later discussion

A `model_run` row is one call:

- **Identity:** capture, photo, job, `purpose` (`ingest`, `refine`, `discuss`) and `parent_id`
  (the turn it continues).
- **Settings:** model and served model, `prompt_version` and the image size sent.
- **`request`:** the system prompt text, the messages and the parameters, with images as
  `{"type": "image", "blob": <sha256>, "sent": {...}}` and never base64.
- **`response`:** the content blocks exactly as returned, thinking blocks and signatures
  included.
- **Outcome:** the sanitised `output` with warnings, `usage`, `cost_microusd`, `status` and
  `error_class`.

A run is 10 to 50 KB. Runs live in the database, so the backup covers them. A run that backs a
version or a later turn cannot be deleted (foreign keys with no action).

**Discuss and refine (M4).** A conversation is a stored message list. Continuing run *R* sends
*R*'s system prompt and messages, *R*'s `response` unchanged as the assistant turn, and one new
user turn (plus the current drawing if a human version is newer). It uses *R*'s model.

- The history is append-only, as thinking blocks require.
- The image is rebuilt from the original and its sha256 checked. If the bytes differ, *R*'s
  output is sent as plain text without the thinking blocks.
- The new run gets `parent_id = R`; a refine stores a new model version.
- Each turn re-sends the image tokens, and prompt caching helps only within a chat.

**MCP (M3).** `read` gives each photo's text, description, kind, drawing and run id. A `context`
tool returns that run with its image.

## Derived results and versions

0002 creates `derived` with versions, replacing the design's "regenerating replaces it":

- **Current version.** Each `(capture, photo, kind)` has at most one current row
  (`superseded_at IS NULL`, a partial unique index). Inserting a current row supersedes the old
  one (a trigger).
- **Immutable.** Rows never change otherwise, and **Restore** inserts a copy.
- **Kinds.** `ocr`, `description` (its `data` keeps the image kind) and `excalidraw` (`data` is
  `{"format": "skeleton" | "scene", "width", "height", "elements"}`). `summary` and `fetched`
  come later.
- **Producer.** The model id with its `run_id`, or `human` with `author`.
- **Reprocess.** A reprocess over a human drawing stores the new drawing already superseded,
  unless the user confirmed the replacement.

**Page fields** come from the first photo, and the user wins:

- **Title.** It is a compare-and-set that adds no revision, so a user editing rev 1 never gets a
  409 because ingest finished:

  ```sql
  UPDATE page SET title = :title, slug = :slug, updated_at = :now
  WHERE id = :page AND deleted_at IS NULL AND title = :provisional
    AND NOT EXISTS (SELECT 1 FROM page_rev WHERE page_id = :page AND rev > 1)
  ```

  - It applies only to the provisional date title of a capture without text, on a page still
    at rev 1.
  - On a hit, the same transaction sets rev 1's title and re-indexes the page.
  - The PWA's edit sends `title` only when the user changed it.
- **Tags** fill an empty tag list on the first success (0002 adds `tag`).
- **Kind** changes only while it is `note` and not fixed: whiteboard and diagram become
  `whiteboard`, document becomes `document`. The mapping is one table in code.

**Search.** A trigger indexes a current version's `text` as a chunk with `derived_id`, and
superseding removes it. That covers OCR, the description and a human drawing's labels; a model
drawing's text is NULL, because its words are the OCR. M1 needs two changes:

- `Store._index` deletes only chunks with `derived_id IS NULL`;
- search groups hits by page.

## Excalidraw in the PWA

- **Loading.** A Vite dynamic `import()` loads `@excalidraw/excalidraw` and React only when a
  drawing opens. That chunk is about 410 kB gzipped; the base app stays about 8 kB.
- **Fonts.** The fonts used are self-hosted through `EXCALIDRAW_ASSET_PATH`. The default fetches
  them from a CDN, and the full set is 14 MB.
- **Conversion.** `convertToExcalidrawElements` expands stored skeletons in the browser, with
  two workarounds from the experiment:
  - an arrow bound to a free text element carries that text's `x`/`y` in `start`/`end`;
  - the scene is converted again after `document.fonts.ready`.
- **Viewing and editing.** View mode by default, beside the photo or in a tab. **Edit** saves the
  full scene with its base version (409 if stale) as a `human` version whose labels become
  `text`. **History** has **Restore**.
- **Export.** `.excalidraw`, PNG and SVG, made in the browser. The image tool is hidden.

**Sanitising.**

*Model output* is strict. A violation drops just that element and records a warning, and the run
fails only if no text and no description remain:

- types `rectangle`, `ellipse`, `diamond`, `text`, `arrow` and `line`;
- ids of up to 32 characters `[A-Za-z0-9_-]`, colours `#rrggbb`;
- finite numbers within a quarter of the image beyond its edges;
- font size 4 to 200, at most 200 points, 2000 characters and 1000 elements.

*Human scenes* are permissive:

- any type but `image`, `embeddable`, `iframe` and `frame`;
- any finite position, freedraw strokes of up to 50,000 points;
- colours as Excalidraw writes them (`transparent`, named, `#rgb`, `#rrggbbaa`, `rgb()`,
  `rgba()`);
- Excalidraw's own keys kept (`index`, `groupIds`, `containerId`, `originalText`, bindings);
- `link` only with http(s);
- 5 MB per scene.

A scene that breaks these gets a 422, nothing silently dropped, and the editor keeps its state.

**Prompt injection.** The image is data. The call has no tools and no network, and its output is
schema-checked and sanitised; nothing in it is fetched or executed. It can change only its own
page's versions (restorable), a provisional title, empty tags and an unfixed `note` kind.

## Spend and outage control

A price table in code turns each run's `usage` into `cost_microusd`. Expect about $0.05 to $0.15
per board, mostly output and thinking; PR 1 measures it.

- **Daily budget.** `SCRAP_BUDGET_DAY_USD` (default 3) pauses the queue (`budget`) until UTC
  midnight.
- **Hard cap.** The Console spend limit. Hitting it also pauses the queue.

| Class | Recognised by | Effect |
| --- | --- | --- |
| credit | 402 `billing_error`; 400 whose message contains "reached your specified" and "API usage limits" (Console spend limit) or "credit balance"; 429 with `error.details.error_code` `enforced_spend_limit_reached` | pause until *Resume* |
| auth | 401, 403, 404 (unknown model) | pause until *Resume* |
| rate limit | any other 429 | pause until `retry-after`, else 1 min |
| outage | any 5xx (incl. 504, 529), connection error, after the SDK's 2 retries | pause 1, 2, 4 ... 60 min |
| timeout | no answer in 240 s | charged; retry in 10 min; dead after 3 |
| content | refusal, any other 400, 413 | charged; dead at once |
| invalid | `max_tokens`, nothing valid left | charged; one immediate retry |

- **Pauses** refund the claim and move the job's `run_after` to the pause's end, so other jobs
  go first afterwards.
- **Six claims** of any kind kill a job ("too many tries"), so no job can hold the head of the
  queue for ever.
- **Breaker.** Three consecutive charged failures on different jobs pause the queue (`failing`)
  until *Resume*, so a misread outage costs at most three tries.
- **Success** clears the pause and the counters.
- **Notification.** The first pause of an episode POSTs once to `SCRAP_NOTIFY_URL` (off when
  unset; an ntfy topic works). The body is fixed text naming only the reason: never titles, OCR
  or API errors.

## Migration 0002 (sketch)

This runs after `0001_init.sql` under the M1 runner, which sets `foreign_keys` on every
connection. Hard deletes cascade; soft delete is handled by the claim and by search. A version
is inserted with `version = (SELECT coalesce(max(version), 0) + 1 ...)` inside
`BEGIN IMMEDIATE`. The app strips control characters from `text`, as M1 does.

```sql
CREATE TABLE tag (
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL CHECK (tag = lower(tag) AND length(tag) BETWEEN 1 AND 64),
    PRIMARY KEY (page_id, tag)
);
CREATE INDEX tag_by_name ON tag(tag);

CREATE TABLE job (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('ingest', 'refine')),
    capture_id    TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    source_sha256 TEXT NOT NULL,               -- the photo
    state         TEXT NOT NULL DEFAULT 'queued'
                    CHECK (state IN ('queued', 'running', 'done', 'dead')),
    attempts      INTEGER NOT NULL DEFAULT 0,  -- claims of any outcome: dead at 6
    failures      INTEGER NOT NULL DEFAULT 0,  -- charged: content errors and timeouts
    options       TEXT NOT NULL DEFAULT '{}' CHECK (json_type(options) = 'object'),
    run_after     TEXT NOT NULL,
    last_error    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX job_ready ON job(state, run_after);
CREATE INDEX job_by_capture ON job(capture_id);
-- One queued or running job per step: enqueue with ON CONFLICT DO NOTHING, so a photo sent
-- twice in one capture, or Reprocess pressed twice, adds nothing.
CREATE UNIQUE INDEX job_one_active ON job(kind, capture_id, source_sha256)
    WHERE state IN ('queued', 'running');

-- One row. A pause stops every claim until paused_until (far future: until Resume).
CREATE TABLE queue_state (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    paused_until  TEXT,                        -- NULL: running
    reason        TEXT CHECK (reason IN
                    ('auth', 'credit', 'rate_limit', 'outage', 'budget', 'failing', 'manual')),
    outages       INTEGER NOT NULL DEFAULT 0,  -- consecutive outage errors: backoff exponent
    streak        INTEGER NOT NULL DEFAULT 0,  -- consecutive charged failures, distinct jobs
    last_failed   INTEGER,                     -- job id of the last charged failure
    notified_at   TEXT,                        -- this pause has been announced
    updated_at    TEXT NOT NULL
);
INSERT INTO queue_state (id, updated_at) VALUES (1, '1970-01-01T00:00:00.000Z');

-- Every model call, kept so a conversation can resume from it. Images are referenced by
-- blob sha256, never embedded.
CREATE TABLE model_run (
    id             INTEGER PRIMARY KEY,
    capture_id     TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    source_sha256  TEXT NOT NULL,
    job_id         INTEGER REFERENCES job(id) ON DELETE SET NULL,
    parent_id      INTEGER REFERENCES model_run(id),  -- the turn this one continues (M4)
    purpose        TEXT NOT NULL CHECK (purpose IN ('ingest', 'refine', 'discuss')),
    backend        TEXT NOT NULL,              -- 'api'
    model          TEXT NOT NULL,              -- requested
    served_model   TEXT,                       -- as reported by the response
    prompt_version TEXT NOT NULL,              -- e.g. photo@3f9c2a1b0d4e
    image_width    INTEGER,                    -- pixels actually sent: the drawing's frame
    image_height   INTEGER,
    request        TEXT NOT NULL CHECK (json_valid(request)),
    response       TEXT CHECK (json_valid(response)),  -- content blocks as returned, stop_reason
    output         TEXT CHECK (json_valid(output)),    -- the sanitised result, with warnings
    usage          TEXT CHECK (json_valid(usage)),
    cost_microusd  INTEGER NOT NULL DEFAULT 0,  -- estimated from usage and a price table
    status         TEXT NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'ok', 'invalid', 'refused', 'error')),
    error_class    TEXT CHECK (error_class IN
                     ('content', 'timeout', 'outage', 'pause', 'budget', 'internal')),
    error          TEXT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT
);
CREATE INDEX model_run_by_source ON model_run(capture_id, source_sha256);
CREATE INDEX model_run_by_started ON model_run(started_at);  -- spend per day

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
    producer, run_id, author, text, data, created_at ON derived BEGIN
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

## Build order

1. **Worker, backend, runs.** First, one real call with the schema and thinking. Then:
   - 0002, the worker (off by default) and `complete()`;
   - the prompt, the model sanitiser and the page rules;
   - the `_index` fix and search grouping;
   - capture state with a PWA badge;
   - OCR and descriptions in `scrap export`.
2. **Excalidraw view.** The lazy chunk, edit with the scene sanitiser, history, restore and
   export, and `.excalidraw` files in the export.
3. **Spend and outage control.** Error classes, pause, breaker, budget, notification, banner.
   Ingest is switched on for daily use after this.
4. **Reprocess UI.** *Reprocess* with its confirmation, *Retry* on failed captures.

**Deferred:**

- MCP (M3), and chat and refine (M4);
- notes, links, files and URL fetching;
- embeddings, and pruning runs.

## Risks and unknowns

- **Untested:** structured output with adaptive thinking, and the flat schema's effect on drawing
  quality. PR 1 tests both first.
- **Excalidraw API drift:** the converter and the 0.18 binding bug may change, so pin the version.
- **Prompt drift:** model changes are traced by `prompt_version` and the served model. Keep the
  experiment's boards as a check set.
- **Replay rules** for thinking blocks have changed before. The plain-text fallback covers a
  rejection.
