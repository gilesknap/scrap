-- A todo's due, priority and snoozed_until move off page into page_todo (ADR 36): one
-- row per page that has at least one of them set. Whether a page is a todo stays
-- page.kind; a row for a page of another kind is a todo turned note, kept hidden.
CREATE TABLE page_todo (
    page_id       TEXT PRIMARY KEY REFERENCES page(id) ON DELETE CASCADE,
    due           TEXT CHECK (due IS NULL OR (length(due) = 10 AND date(due) = due)),
    priority      TEXT CHECK (priority IN ('high', 'medium', 'low')),
    snoozed_until TEXT CHECK (snoozed_until IS NULL OR
                      (length(snoozed_until) = 10 AND date(snoozed_until) = snoozed_until)),
    CHECK (due IS NOT NULL OR priority IS NOT NULL OR snoozed_until IS NOT NULL)
) WITHOUT ROWID;

CREATE INDEX page_todo_by_due ON page_todo(due) WHERE due IS NOT NULL;
CREATE INDEX page_todo_by_snooze ON page_todo(snoozed_until)
    WHERE snoozed_until IS NOT NULL;

INSERT INTO page_todo (page_id, due, priority, snoozed_until)
    SELECT id, due, priority, snoozed_until FROM page
    WHERE due IS NOT NULL OR priority IS NOT NULL OR snoozed_until IS NOT NULL;

DROP INDEX page_by_due;
DROP INDEX page_by_snooze;
ALTER TABLE page DROP COLUMN due;
ALTER TABLE page DROP COLUMN priority;
ALTER TABLE page DROP COLUMN snoozed_until;
