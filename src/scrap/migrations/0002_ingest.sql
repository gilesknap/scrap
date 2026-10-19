-- M2: Claude ingest. Jobs and the queue's pause state, every model call (the context a later
-- conversation replays), derived results as versions, tags, and search over derived text.
-- Applied in one transaction; the runner then sets PRAGMA user_version = 2.

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
