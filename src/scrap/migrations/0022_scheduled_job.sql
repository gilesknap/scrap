-- scrap schedule's jobs with Litestream (ADR 46, #558): each job's last run, one row a
-- job, kept in the database so it survives the pod (the emptyDir is restored from the
-- replica). Read by scrap schedule status and its metrics. Times are UTC ISO text.
-- result is ok, failed, deadline, not-started, paused or stopped (scrap.schedule_record);
-- no CHECK, so a new one needs no table rebuild.
CREATE TABLE scheduled_job (
    name        TEXT PRIMARY KEY,
    seen_at     TEXT NOT NULL,  -- first known to the scheduler: staleness counts from it
    started_at  TEXT,           -- the last start, of the run going now if there is one
    finished_at TEXT,           -- the last run's end
    result      TEXT,           -- and how it ended
    exit_code   INTEGER,
    ok_at       TEXT            -- the end of the last run that succeeded
);
