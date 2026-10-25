"""Data fixes that run after a numbered schema migration."""

import json
import sqlite3

from ..markdown import tasks
from .helpers import tag_path, todo_columns
from .indexing import index_page


def move_todo_fields(conn: sqlite3.Connection) -> None:
    """Each todo's due and priority fields (as imported from Thoth) into its columns."""
    for page_id, fields in conn.execute(
        "SELECT id, fields FROM page WHERE kind = 'todo'"
    ).fetchall():
        todo, rest = todo_columns("todo", json.loads(fields))
        if any(todo.values()):
            conn.execute(
                "UPDATE page SET due = ?, priority = ?, fields = ? WHERE id = ?",
                (todo["due"], todo["priority"], json.dumps(rest), page_id),
            )


def add_snooze(conn: sqlite3.Connection) -> None:
    """A todo's snoozed_until (migration 6), unless an earlier run added it."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(page)")}
    if "snoozed_until" not in columns:
        conn.execute(
            "ALTER TABLE page ADD COLUMN snoozed_until TEXT CHECK (snoozed_until"
            " IS NULL OR (length(snoozed_until) = 10"
            " AND date(snoozed_until) = snoozed_until))"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS page_by_snooze ON page(snoozed_until)"
        " WHERE snoozed_until IS NOT NULL"
    )


def add_tasks(conn: sqlite3.Connection) -> None:
    """Each page's task box counts (migration 7): the columns if missing, counted."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(page)")}
    for name in ("task_done", "task_total"):
        if name not in columns:
            conn.execute(
                f"ALTER TABLE page ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0"
            )
    for page_id, body in conn.execute("SELECT id, body FROM page").fetchall():
        conn.execute(
            "UPDATE page SET task_done = ?, task_total = ? WHERE id = ?",
            (*tasks(body), page_id),
        )


def add_meta_revs(conn: sqlite3.Connection) -> None:
    """The revisions of pages' kinds and tags (migration 8), unless an earlier run made
    them. tags_* are JSON arrays, sorted; fixed_* the page's kind_fixed; fields_added
    the default fields a new kind added (a revert takes them off); reverts the
    revision a revert undid; batch_id shared by one bulk change's revisions."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS page_meta_rev ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"  # an id is never used again
        " page_id TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,"
        " author TEXT NOT NULL,"
        " source TEXT NOT NULL CHECK (source IN ('web', 'mcp')),"
        " kind_before TEXT NOT NULL,"
        " kind_after TEXT NOT NULL,"
        " fixed_before INTEGER NOT NULL CHECK (fixed_before IN (0, 1)),"
        " fixed_after INTEGER NOT NULL CHECK (fixed_after IN (0, 1)),"
        " tags_before TEXT NOT NULL CHECK (json_type(tags_before) = 'array'),"
        " tags_after TEXT NOT NULL CHECK (json_type(tags_after) = 'array'),"
        " fields_added TEXT NOT NULL DEFAULT '{}'"
        "  CHECK (json_type(fields_added) = 'object'),"
        " reverts INTEGER REFERENCES page_meta_rev(id),"
        " batch_id TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL)"
    )
    for name, columns in (
        ("by_page", "page_id, id"), ("by_reverts", "reverts"), ("by_batch", "batch_id"),
    ):  # fmt: skip
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS page_meta_rev_{name}"
            f" ON page_meta_rev({columns})"
        )


# The enrich job table (named), and its indexes; reason 'related' since migration 11
ENRICH_JOB = """
CREATE TABLE IF NOT EXISTS {name} (
    id          INTEGER PRIMARY KEY,
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    reason      TEXT NOT NULL CHECK (reason IN ('capture', 'save', 'ask', 'backfill',
                                                'related')),
    state       TEXT NOT NULL DEFAULT 'queued'
                  CHECK (state IN ('queued', 'running', 'done', 'dead')),
    failures    INTEGER NOT NULL DEFAULT 0,
    run_after   TEXT NOT NULL,
    last_error  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""
ENRICH_JOB_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS enrich_job_one_queued ON enrich_job(page_id)
    WHERE state = 'queued';
CREATE INDEX IF NOT EXISTS enrich_job_ready ON enrich_job(state, run_after);
"""
ENRICH_TABLES = (
    ENRICH_JOB.format(name="enrich_job")
    + ";"
    + ENRICH_JOB_INDEXES
    + """
CREATE TABLE IF NOT EXISTS enrich_run (
    id             INTEGER PRIMARY KEY,
    page_id        TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    job_id         INTEGER REFERENCES enrich_job(id) ON DELETE SET NULL,
    model          TEXT NOT NULL,
    served_model   TEXT,
    prompt_version TEXT NOT NULL,
    request        TEXT NOT NULL CHECK (json_valid(request)),
    response       TEXT CHECK (json_valid(response)),
    output         TEXT CHECK (json_valid(output)),
    usage          TEXT CHECK (json_valid(usage)),
    cost_microusd  INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'ok', 'invalid', 'refused', 'error')),
    error_class    TEXT,
    error          TEXT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT
);
CREATE INDEX IF NOT EXISTS enrich_run_by_started ON enrich_run(started_at);
CREATE INDEX IF NOT EXISTS enrich_run_by_page ON enrich_run(page_id);
CREATE TABLE IF NOT EXISTS enrichment (
    page_id     TEXT PRIMARY KEY REFERENCES page(id) ON DELETE CASCADE,
    run_id      INTEGER REFERENCES enrich_run(id),
    producer    TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    source      TEXT,
    source_title TEXT,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_tag (
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    state       TEXT NOT NULL CHECK (state IN ('on', 'off')),
    producer    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (page_id, tag)
);
CREATE TABLE IF NOT EXISTS related (
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    other_id    TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    rank        INTEGER NOT NULL,
    PRIMARY KEY (page_id, other_id)
);
CREATE INDEX IF NOT EXISTS related_by_other ON related(other_id);
"""
)


def add_enrich(conn: sqlite3.Connection) -> None:
    """Enrich's tables (migration 9), unless an earlier run made them."""
    for statement in ENRICH_TABLES.split(";"):
        if statement.strip():
            conn.execute(statement)


def add_related_reason(conn: sqlite3.Connection) -> None:
    """Migration 11: enrich_job takes reason 'related' (a page's first related call,
    once it is first read), the table rebuilt for its CHECK, unless it takes it
    already. Dropping the old table clears enrich_run.job_id (ON DELETE SET NULL), so
    the runs' jobs are kept aside and put back."""
    (sql,) = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'enrich_job'"
    ).fetchone()
    if "'related'" in sql:
        return
    conn.execute(
        "CREATE TEMP TABLE run_job AS"
        " SELECT id, job_id FROM enrich_run WHERE job_id IS NOT NULL"
    )
    conn.execute(ENRICH_JOB.format(name="enrich_job_new"))
    conn.execute(
        "INSERT INTO enrich_job_new SELECT id, page_id, reason, state, failures,"
        " run_after, last_error, created_at, updated_at FROM enrich_job"
    )
    conn.execute("DROP TABLE enrich_job")
    conn.execute("ALTER TABLE enrich_job_new RENAME TO enrich_job")
    for statement in ENRICH_JOB_INDEXES.split(";"):
        if statement.strip():
            conn.execute(statement)
    conn.execute(
        "UPDATE enrich_run SET job_id = (SELECT t.job_id FROM temp.run_job t"
        " WHERE t.id = enrich_run.id) WHERE id IN (SELECT id FROM temp.run_job)"
    )
    conn.execute("DROP TABLE temp.run_job")


def fix_tag_paths(conn: sqlite3.Connection) -> None:
    """Migration 10 (#87): tags with an empty path segment (/lead, trail/, a//b) as
    clean_tags now writes them, and the pages concerned indexed again. Cost: a scan of
    the tag tables and a reindex of those pages only (normally none). Revision history
    keeps the old names."""
    bad = "tag LIKE '/%' OR tag LIKE '%/' OR tag LIKE '%//%'"
    touched: set[str] = set()
    for table in ("tag", "model_tag"):
        for page_id, tag in conn.execute(
            f"SELECT page_id, tag FROM {table} WHERE {bad}"
        ).fetchall():
            new = tag_path(tag)
            if new:  # a page that has the new name already keeps one row
                conn.execute(
                    f"UPDATE OR IGNORE {table} SET tag = ?"
                    " WHERE page_id = ? AND tag = ?",
                    (new, page_id, tag),
                )
            conn.execute(
                f"DELETE FROM {table} WHERE page_id = ? AND tag = ?", (page_id, tag)
            )
            touched.add(page_id)
    for page_id in touched:
        index_page(conn, page_id)
