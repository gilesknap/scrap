-- Todo richness (#104): a todo's due date and priority, as typed columns so that filters
-- (due:, priority:) and sorts (sort:due, sort:priority) stay simple and indexable. Both
-- belong to the todo kind: a page of another kind keeps them (a stray kind tap loses
-- nothing) but they are ignored there. due is a calendar day (YYYY-MM-DD), no time or time
-- zone; priority is high, medium or low. The runner then moves the due and priority fields
-- an imported todo carries into these columns, in Python, in this same transaction
-- (store.AFTER[5]), and sets PRAGMA user_version = 5.

ALTER TABLE page ADD COLUMN due TEXT
    CHECK (due IS NULL OR (length(due) = 10 AND date(due) = due));
ALTER TABLE page ADD COLUMN priority TEXT
    CHECK (priority IN ('high', 'medium', 'low'));
CREATE INDEX page_by_due ON page(due) WHERE due IS NOT NULL;
