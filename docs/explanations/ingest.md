# Claude ingest (M2)

Status: design for milestone 2. It builds on the M1 code on `main` (`0001_init.sql`, `store.py`,
`app.py`) and the PWA, and supersedes parts of [the design](design.md) listed there.

M2 sends each photo to Claude once for its text, description, kind, title, tags and an
Excalidraw drawing. Each result is a version that can be regenerated, edited or discussed;
every call is stored, so a chat in the PWA (M4) or an MCP session (M3) starts from what the
model saw and said.

**Settled:** the Messages API only, on Opus; photos only; Reprocess always asks before replacing
a human drawing; the image kind is stored as given (issue #11 does not block); $3 a day.

**Cut:** a `claude -p` backend (needs a Read tool; `complete()` is the seam), a cheaper
first-pass model, a monthly budget (the Console limit caps it), a circuit breaker and a
rate-limit class (the budget and **Retry** cover them).

## Worker

One daemon thread from the FastAPI lifespan: `Store` is synchronous and SQLite has one writer,
so no asyncio task or second process. `SCRAP_INGEST=off` (the default until spend control lands)
leaves it unstarted. The capture transaction enqueues one job per distinct image of a photo:

```sql
INSERT INTO job (kind, capture_id, source_sha256, run_after, created_at, updated_at)
SELECT DISTINCT 'ingest', cb.capture_id, cb.sha256, :now, :now, :now
FROM capture_blob cb
JOIN capture c ON c.id = cb.capture_id AND c.kind = 'photo'
JOIN blob b ON b.sha256 = cb.sha256 AND b.mime LIKE 'image/%'
WHERE cb.capture_id = :capture
ON CONFLICT DO NOTHING
```

`job_one_active` makes a repeated photo or a second *Reprocess* add nothing. The thread wakes
on enqueue or every 30 s and claims the oldest ready job whose page is not in the trash, unless
the queue is paused:

```sql
UPDATE job SET state = 'running', updated_at = :now
WHERE id = (
    SELECT j.id FROM job j
    JOIN capture c ON c.id = j.capture_id
    JOIN page p ON p.id = c.page_id
    WHERE j.state = 'queued' AND j.run_after <= :now AND p.deleted_at IS NULL
    ORDER BY j.run_after, j.id LIMIT 1)
  AND NOT EXISTS (SELECT 1 FROM queue_state WHERE paused_until > :now)
RETURNING id, capture_id, source_sha256, failures
```

One job runs at a time (11 to 55 s per board): insert a `model_run` row, call Claude holding
no lock, then in one `BEGIN IMMEDIATE` re-read the job (a purge counts as done), finish the run,
write the versions and page fields, and mark the job `done` or apply the error rules. The loop
catches every exception, so the thread cannot die silently; `/healthz` fails if it does. A
`running` job found at service start is charged as `crashed` (it may have killed the process),
so a crashing job cannot loop the service. The PWA shows each capture *queued*, *processing*, *done*, *failed* (reason and
**Retry**) or *paused*, a **Reprocess** per photo, and a banner with **Resume** while paused.

## The Claude call

`complete(model, system, messages, schema)` returns the sanitised JSON, the raw content blocks,
the usage and the served model.

- The `anthropic` SDK, with `ANTHROPIC_API_KEY` from the service user's mode-600 env file; no
  `tools`; SDK debug logging off (it logs request bodies).
- Error text is stored and shown only after redaction: anything shaped like an API key, and the
  key itself, is removed, in case a server or proxy ever echoes the request headers.
- `max_retries=0` and a 240 s request timeout: the queue does all retrying, so one claim is one
  call. The SDK's own retries would triple a timeout and repeat a spend-cap 429 that cannot
  succeed.
- `SCRAP_VISION_MODEL`, default `claude-opus-5-5` (best on handwriting in the experiment). Its
  thinking cannot be disabled, so `effort` is set explicitly (`medium` to start) and recorded.
  `max_tokens` is 16000.

**Image.** Claude never gets the original, but a JPEG made from it (EXIF orientation applied,
HEIC converted, quality 85). It is made by the preview code, one decode at a time and within
its memory budget, so an image too large to decode is refused from its header. It is scaled to the largest size with a long edge of at most
2048 px and ⌈w/28⌉·⌈h/28⌉ ≤ 4784 image tokens, the high-resolution cap:

- a 4:3 photo is sent as 2048×1536 (4070 tokens);
- a square one as 1932×1932.

The image block sets `"transformations": {"oversized_image": "error"}`, so the API never
rescales it silently (verified: a 2048×2048 image is refused with a 400 naming 1932×1932 as the
largest size; 1932×1932 is accepted at 4781 input tokens), and drawing coordinates are in sent pixels. The JPEG is
stored as a blob (`model_run.sent_sha256`) with its `image_width` and `image_height`. The PWA
scales the drawing to the displayed photo, and M4 replays the exact bytes. A later `scrap gc`
must count `sent_sha256` as in use; after a purge it is an orphan that gc removes.

**Output:** `kind` (whiteboard, diagram, handwriting, screenshot, document, photo or other),
`title`, `tags`, `description`, `text` (one item per line, `(?)` after uncertain readings) and
`elements` (empty unless whiteboard or diagram). The prompt grows from the experiment's
`skeleton_v3` and lives in `src/scrap/prompts/`; `prompt_version` is `<name>@<12 hex digits of
sha256(prompt + schema)>`.

**Schema.** It keeps to the documented structured-output subset (`additionalProperties: false`,
no numeric or string bounds, `minItems` 0 or 1, at most 24 optional and 16 union properties),
which the experiment's `[x, y]` tuples broke. An element is one flat object: `type`, `id`, `x`,
`y` required, plus 11 optional scalars or number lists, none a union: `width`, `height`,
`text`, `fontSize`, `label`, `labelFontSize`, `points` (flat `[dx0, dy0, dx1, dy1, ...]`),
`start` and `end` (shape ids), `strokeColor`, `startArrowhead`. Code makes Excalidraw skeletons
of these and the sanitiser enforces bounds. Verified on `claude-opus-5-5` (4 calls on real
boards, `thinking` omitted so adaptive, effort `medium`): the API takes this schema with
thinking on, every output was valid JSON first try, and the model chose not to think at all
(0 thinking tokens, no thinking blocks). With `id` optional the model left out every id and
every arrow on a box-and-arrow board, so `id` is required and the prompt asks for every arrow.

## Stored context for later discussion

A `model_run` row is one call (columns in the SQL below). `request` holds the system prompt,
messages and parameters, with images as blob references, never base64; `response` holds the
content blocks exactly as returned, thinking blocks and signatures included. A run (10 to 50 KB)
cannot be deleted while a version or later turn uses it.

**Discuss and refine (M4).** Continuing run *R* sends *R*'s system prompt and messages (the
stored JPEG, byte for byte), *R*'s `response` unchanged as the assistant turn, and one new user
turn (plus the current drawing if a human version is newer), on *R*'s model. The history is
append-only, as thinking blocks require. The new run gets `parent_id = R`; a refine stores a new
model version. Each turn re-sends the image tokens.

**MCP (M3).** `read` gives each photo's text, description, kind, drawing and run id; a `context`
tool returns that run with its image.

## Derived results and versions

0002 creates `derived` with versions, replacing the design's "regenerating replaces it":

- One current row (`superseded_at IS NULL`, a partial unique index) per `(capture, photo,
  kind)`; inserting one supersedes the old (a trigger). Rows never change otherwise;
  **Restore** inserts a copy.
- **Kinds.** `ocr`, `description` (its `data` keeps the image kind) and `excalidraw` (`data` is
  `{"format": "skeleton" | "scene", "width", "height", "elements"}`). `summary` and `fetched`
  come later.
- **Producer:** the model id with its `run_id`, or `human` with `author`. A reprocess over a
  human drawing stores its drawing already superseded unless the user confirmed. The
  confirmation is kept on a job already queued or running (the worker reads it as it
  finishes), so it is never lost (issue #19).
- **Restore** copies the version's producer, run, author and text; its `data` adds
  `restored_from` (the version) and `restored_by`, so the history can say so.

**Page fields** come from the first photo, and the user wins:

- **Title.** The provisional title is M1's (first line of text, else the URL, else the device
  date) and stays in rev 1 as captured. Only the first photo of a capture without text may
  replace it, once, on the page row only, adding no revision:

  ```sql
  UPDATE page SET title = :title, updated_at = :now
  WHERE id = :page AND deleted_at IS NULL
    AND title = (SELECT title FROM page_rev WHERE page_id = :page AND rev = 1)
    AND NOT EXISTS (SELECT 1 FROM page_rev WHERE page_id = :page AND rev > 1)
    AND EXISTS (SELECT 1 FROM capture c WHERE c.id = :capture AND c.page_id = :page
                AND c.text IS NULL AND :photo = (SELECT sha256 FROM capture_blob
                                                 WHERE capture_id = c.id ORDER BY ord LIMIT 1))
  ```

  The same transaction re-indexes the page. `PATCH /api/pages/{id}` treats a title equal to the
  title at its `base_rev` as unchanged, so the PWA, which always sends the title it loaded,
  never undoes the model's. The PWA should still send `title` only when edited (issue #13), but
  the server does not depend on it. The slug never changes (the PWA uses the id).
- **Tags** fill an empty tag list on the first success (0002 adds `tag`).
- **Kind** changes only while it is `note` and not fixed: whiteboard and diagram become
  `whiteboard`, document becomes `document`. The mapping is one table in code.

**Search.** A trigger indexes a current version's `text` as a chunk with `derived_id`, and
superseding removes it. That covers OCR, the description and a human drawing's labels; a model
drawing's text is NULL, because its words are the OCR. M1 needs two changes:

- `Store._index` deletes only chunks with `derived_id IS NULL`;
- search groups hits by page, in a subquery or in Python, since `bm25()` and `snippet()` refuse
  `GROUP BY`.

## Excalidraw in the PWA

A Vite dynamic `import()` loads `@excalidraw/excalidraw` and React (about 410 kB gzipped) only
when a drawing opens; the base app stays about 8 kB. Only the fonts used are self-hosted
(`EXCALIDRAW_ASSET_PATH`; the default is a CDN, the full set 14 MB). `convertToExcalidrawElements`
expands skeletons in the browser with the experiment's two workarounds: an arrow bound to free
text carries that text's `x`/`y` in `start`/`end`, and the scene is converted again after
`document.fonts.ready`. View mode by default, beside the photo; **Edit** saves the scene with its
base version (409 if stale) as a `human` version whose labels become `text`; **History** has
**Restore**; export to `.excalidraw`, PNG and SVG; the image tool is hidden.

**Sanitising.**

*Model output* is strict; a violation drops just that element, with a warning in the run:

- types `rectangle`, `ellipse`, `diamond`, `text`, `arrow` and `line`;
- ids of up to 32 characters `[A-Za-z0-9_-]`, colours `#rrggbb`;
- finite numbers within a quarter of the image beyond its edges;
- font size 4 to 200, at most 200 points, 2000 characters and 1000 elements;
- an arrow whose `start` or `end` names no remaining element loses that binding.

*Human scenes* are permissive:

- types from an allowlist: the six above plus `freedraw` (no images, embeds or frames);
- any finite position, freedraw strokes of up to 50,000 points;
- any colour Excalidraw writes (`transparent`, named, `#rgb`, `#rrggbbaa`, `rgba()`), and its
  own keys (`index`, `groupIds`, `containerId`, `originalText`, bindings);
- `link` only with http(s), and the scene's `files` map (embedded image data) stripped;
- 5 MB per scene (as compact JSON), nested at most 32 levels deep (deeper JSON could be
  stored, then never served).

A scene that breaks these gets a 422, and the editor keeps its state.

**Prompt injection.** The image is data: no tools, no network, output schema-checked and
sanitised. It can change only its page's versions, a provisional title, empty tags and an
unfixed `note` kind.

## Spend and outage control

A price table turns each run's `usage` into `cost_microusd` (measured: $0.03 to $0.06 a board,
about 6900 input tokens and 150 to 1500 output tokens, 3 to 39 s). The budget is `SCRAP_BUDGET_DAY_USD` (default 3); the Console spend limit is
the hard cap.

| Class | Recognised by | Effect |
| --- | --- | --- |
| credit | 402 `billing_error`; 400 whose message contains "reached your specified" and "API usage limits" (Console spend limit) or "credit balance"; 429 with `error.details.error_code` `enforced_spend_limit_reached` | pause until *Resume* (wording from the docs, not provoked) |
| auth | 401 (verified: `authentication_error`, "invalid x-api-key"), 403, 404 (unknown model) | pause until *Resume* |
| outage | any other 429; any 5xx (incl. 504, 529); connection error | pause until `retry-after` (at most 1 h), else 1, 2, 4 ... 60 min |
| budget | the day's spend reached | pause until UTC midnight |
| timeout | `APITimeoutError` (240 s) | charged |
| invalid | `max_tokens`, bad output, nothing valid left (no text and no description: bad drawing elements are only dropped) | charged; retried at once |
| content | refusal, any other 400, 409, 413, 422 | charged |
| image | decode or HEIC failure, too large to decode within the preview code's memory budget | charged |
| internal | any other exception | charged |
| crashed | `running` at service start | charged |

**The rule.** A pause refunds the claim: the job stays `queued` with `run_after` set to the
failure's time, behind older jobs, while the pause gate waits. *Resume*, or the pause running
out, makes it claimable again, so an outage fails nothing. Every charged failure adds 1 to
`job.failures` and retries 10 minutes later (invalid output at once); the third kills the job.
The SDK's `APITimeoutError` subclasses `APIConnectionError`, so it is tested first, else every
timeout would be a free outage retry. A success clears the pause. The first pause of an
episode (or a pause for a new reason, such as a spend limit after a budget pause) POSTs once to `SCRAP_NOTIFY_URL` (off when unset; an ntfy topic works) with fixed text
naming only the reason, never titles, OCR or API errors.

## Migration 0002 (sketch)

Runs after `0001_init.sql` under the M1 runner (`foreign_keys` on every connection). A version
is inserted with `version = (SELECT coalesce(max(version), 0) + 1 ...)` in `BEGIN IMMEDIATE`;
the app strips control characters from `text`, as M1 does.

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
    failures      INTEGER NOT NULL DEFAULT 0,  -- charged failures (all but pauses): dead at 3
    options       TEXT NOT NULL DEFAULT '{}' CHECK (json_type(options) = 'object'),
    run_after     TEXT NOT NULL,
    last_error    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX job_ready ON job(state, run_after);
CREATE INDEX job_by_capture ON job(capture_id);
-- One queued or running job per photo (enqueue with ON CONFLICT DO NOTHING).
CREATE UNIQUE INDEX job_one_active ON job(kind, capture_id, source_sha256)
    WHERE state IN ('queued', 'running');

-- One row. A pause stops every claim until paused_until (far future: until Resume).
CREATE TABLE queue_state (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    paused_until  TEXT,                        -- NULL: running
    reason        TEXT CHECK (reason IN ('auth', 'credit', 'outage', 'budget')),
    outages       INTEGER NOT NULL DEFAULT 0,  -- consecutive outage errors: backoff exponent
    notified_at   TEXT,                        -- this pause has been announced
    updated_at    TEXT NOT NULL
);
INSERT INTO queue_state (id, updated_at) VALUES (1, '1970-01-01T00:00:00.000Z');

-- Every model call, kept so a conversation can resume from it.
CREATE TABLE model_run (
    id             INTEGER PRIMARY KEY,
    capture_id     TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    source_sha256  TEXT NOT NULL,
    job_id         INTEGER REFERENCES job(id) ON DELETE SET NULL,
    parent_id      INTEGER REFERENCES model_run(id),  -- the turn this one continues (M4)
    purpose        TEXT NOT NULL CHECK (purpose IN ('ingest', 'refine', 'discuss')),
    model          TEXT NOT NULL,              -- requested
    served_model   TEXT,
    prompt_version TEXT NOT NULL,
    sent_sha256    TEXT REFERENCES blob(sha256),  -- the JPEG actually sent, kept for replay
    image_width    INTEGER,                    -- its pixels: the drawing's frame
    image_height   INTEGER,
    request        TEXT NOT NULL CHECK (json_valid(request)),
    response       TEXT CHECK (json_valid(response)),  -- content blocks as returned
    output         TEXT CHECK (json_valid(output)),    -- the sanitised result, with warnings
    usage          TEXT CHECK (json_valid(usage)),
    cost_microusd  INTEGER NOT NULL DEFAULT 0,  -- from usage and a price table
    status         TEXT NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'ok', 'invalid', 'refused', 'error')),
    error_class    TEXT CHECK (error_class IN
                     ('credit', 'auth', 'outage', 'budget', 'timeout', 'invalid', 'content',
                      'image', 'internal', 'crashed')),
    error          TEXT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT
);
CREATE INDEX model_run_by_source ON model_run(capture_id, source_sha256);
CREATE INDEX model_run_by_started ON model_run(started_at);  -- spend per day

-- Results as versions: one current row (superseded_at IS NULL) per (capture, photo, kind).
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
    data          TEXT CHECK (json_valid(data)),  -- excalidraw: {"format": ..., "elements": ...}
    superseded_at TEXT,                        -- NULL: the current version
    created_at    TEXT NOT NULL,
    UNIQUE (capture_id, source_sha256, kind, version)
);
CREATE UNIQUE INDEX derived_current ON derived(capture_id, source_sha256, kind)
    WHERE superseded_at IS NULL;
CREATE INDEX derived_by_run ON derived(run_id);

-- A current insert supersedes the previous one; insert superseded to keep history only.
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

-- Search: a current version's text is a chunk of its page; the page's own has derived_id NULL.
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

1. **Worker, backend, runs:** one real call with schema and thinking first; then 0002, the
   worker (off), `complete()`, prompt, model sanitiser, page rules with the PATCH title rule,
   the `_index` fix, search grouping, a status badge, OCR and descriptions in `scrap export`.
2. **Excalidraw view:** the lazy chunk, edit with the scene sanitiser, history, restore,
   export, `.excalidraw` in the export.
3. **Spend and outage control:** error classes, pause, budget, notification, banner. Ingest goes
   on for daily use after this.
4. **Reprocess UI:** *Reprocess* with its confirmation, *Retry*.

Deferred: MCP (M3), chat and refine (M4), notes, links, files, URL fetching, embeddings, run
pruning.

## Risks

Thinking: at effort `medium` with structured output the model did not think on any board
(raise the effort if drawings fall short); Excalidraw API drift (pin the version); model
drift (`prompt_version` traces it; keep the experiment's boards as a check set).
