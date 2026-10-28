-- Generated content keeps only its current version (ADR 39): one write-up per page,
-- and no superseded model readings. Drawing versions (derived kind excalidraw) stay.
DELETE FROM writeup WHERE superseded_at IS NOT NULL;

DROP TRIGGER writeup_supersede;
DROP TRIGGER writeup_immutable;
DROP TRIGGER writeup_once;
DROP INDEX writeup_current;
DROP INDEX writeup_by_run;

CREATE TABLE writeup_new (
    page_id        TEXT PRIMARY KEY REFERENCES page(id) ON DELETE CASCADE,
    producer       TEXT NOT NULL,
    run_id         INTEGER REFERENCES enrich_run(id),
    prompt_version TEXT NOT NULL,
    summary        TEXT NOT NULL DEFAULT '',
    text           TEXT NOT NULL,
    guidance       TEXT,
    created_at     TEXT NOT NULL
);
INSERT INTO writeup_new (page_id, producer, run_id, prompt_version, summary, text,
                         guidance, created_at)
SELECT page_id, producer, run_id, prompt_version, summary, text, guidance, created_at
FROM writeup;
DROP TABLE writeup;
ALTER TABLE writeup_new RENAME TO writeup;
CREATE INDEX writeup_by_run ON writeup(run_id);

-- A superseded reading has no chunk (derived_unindex removed it), so only the row goes
DELETE FROM derived WHERE superseded_at IS NOT NULL AND kind <> 'excalidraw';
