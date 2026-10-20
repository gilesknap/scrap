-- Spend (#19): an append-only ledger of every paid model call, kept apart from model_run so a
-- purge (which cascades a page's runs) or a rolled-back result never lowers what was spent; the
-- monthly cap's notices, once per month each; and a 'cap' pause reason. Forward-only: the runs
-- recorded so far are copied into the ledger. The runner then sets PRAGMA user_version = 4.

CREATE TABLE spend (
    id             INTEGER PRIMARY KEY,
    attempt        TEXT NOT NULL UNIQUE,          -- one paid call: a ULID ('run:<id>' if copied)
    purpose        TEXT NOT NULL,                 -- ingest, refine, discuss, ...
    model          TEXT NOT NULL,                 -- served, else requested
    run_id         INTEGER,                       -- no foreign key: a purge keeps the spend
    state          TEXT NOT NULL CHECK (state IN ('reserved', 'settled')),
    estimate_microusd INTEGER NOT NULL,           -- the worst case, held while reserved
    cost_microusd  INTEGER NOT NULL,              -- counted: the estimate until settled
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    flag           TEXT CHECK (flag IN ('unpriced', 'estimated')),  -- NULL: priced from usage
    at             TEXT NOT NULL,                 -- when the call was admitted (UTC)
    settled_at     TEXT
);
CREATE INDEX spend_by_at ON spend(at);

-- Never deleted; a row changes once, from reserved to settled.
CREATE TRIGGER spend_append_only BEFORE DELETE ON spend BEGIN
    SELECT RAISE(ABORT, 'the spend ledger is append-only');
END;
CREATE TRIGGER spend_settled_once BEFORE UPDATE ON spend
WHEN old.state <> 'reserved' BEGIN
    SELECT RAISE(ABORT, 'a settled spend row never changes');
END;

-- One row per notice sent: 'warn' at 80% of the monthly cap, 'cap' when it is reached.
CREATE TABLE spend_notice (
    month   TEXT NOT NULL,                        -- YYYY-MM, UTC
    level   TEXT NOT NULL CHECK (level IN ('warn', 'cap')),
    at      TEXT NOT NULL,
    PRIMARY KEY (month, level)
);

INSERT INTO spend (attempt, purpose, model, run_id, state, estimate_microusd, cost_microusd,
                   input_tokens, output_tokens, cache_write_tokens, cache_read_tokens, at,
                   settled_at)
SELECT 'run:' || id, purpose, coalesce(served_model, model), id, 'settled', cost_microusd,
       cost_microusd,
       coalesce(json_extract(usage, '$.input_tokens'), 0),
       coalesce(json_extract(usage, '$.output_tokens'), 0),
       coalesce(json_extract(usage, '$.cache_creation_input_tokens'), 0),
       coalesce(json_extract(usage, '$.cache_read_input_tokens'), 0),
       started_at, coalesce(finished_at, started_at)
FROM model_run WHERE cost_microusd > 0;

-- queue_state gains the reason 'cap' (a CHECK cannot be altered: the one row is copied).
CREATE TABLE queue_state_new (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    paused_until  TEXT,                        -- NULL: running
    reason        TEXT CHECK (reason IN ('auth', 'credit', 'outage', 'budget', 'cap')),
    outages       INTEGER NOT NULL DEFAULT 0,  -- consecutive outage errors: backoff exponent
    notified_at   TEXT,                        -- this pause has been announced
    updated_at    TEXT NOT NULL
);
INSERT INTO queue_state_new SELECT id, paused_until, reason, outages, notified_at, updated_at
FROM queue_state;
DROP TABLE queue_state;
ALTER TABLE queue_state_new RENAME TO queue_state;
