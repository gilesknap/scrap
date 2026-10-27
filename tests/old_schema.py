"""Putting a migrated test database back to a schema before migration 0018.

Several tests stand for an older scrap that ran on the database in between: they set
user_version back, then migrate again. Migration 0018 moves data and is not one to run
twice, so such a test first calls undo_0018, which rebuilds the todo columns on page
from page_todo (the shape the older scrap saw)."""

import sqlite3

DATE = "{n} IS NULL OR (length({n}) = 10 AND date({n}) = {n})"


def undo_0018(conn: sqlite3.Connection) -> None:
    """The todo columns and indexes back on page, filled from page_todo, which goes."""
    for sql in (
        f"ALTER TABLE page ADD COLUMN due TEXT CHECK ({DATE.format(n='due')})",
        "ALTER TABLE page ADD COLUMN priority TEXT"
        " CHECK (priority IN ('high', 'medium', 'low'))",
        "ALTER TABLE page ADD COLUMN snoozed_until TEXT"
        f" CHECK ({DATE.format(n='snoozed_until')})",
        "UPDATE page SET (due, priority, snoozed_until) = (SELECT due, priority,"
        " snoozed_until FROM page_todo WHERE page_id = page.id)"
        " WHERE id IN (SELECT page_id FROM page_todo)",
        "DROP TABLE page_todo",
        "CREATE INDEX page_by_due ON page(due) WHERE due IS NOT NULL",
        "CREATE INDEX page_by_snooze ON page(snoozed_until)"
        " WHERE snoozed_until IS NOT NULL",
    ):
        conn.execute(sql)
