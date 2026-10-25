"""The database: connections, transactions, schema migrations."""

import fcntl
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from importlib.resources import files as package_files
from pathlib import Path
from typing import Any

from .fixes import (
    add_enrich,
    add_meta_revs,
    add_related_reason,
    add_snooze,
    add_tasks,
    fix_tag_paths,
    move_todo_fields,
)
from .indexing import index_all


def migrations() -> list[str]:
    """The numbered migration scripts, in order: script N sets user_version N."""
    folder = package_files("scrap") / "migrations"
    scripts = sorted((p for p in folder.iterdir() if p.name.endswith(".sql")), key=str)
    return [p.read_text() for p in scripts]


def connect(db: Path | str) -> sqlite3.Connection:
    """Open the database in autocommit mode with the per-connection pragmas."""
    conn = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _rows(conn: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, args)]


def schema_version(db: Path) -> int:
    """A database's schema version, refusing one newer than this code knows."""
    conn = connect(db)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    if version > len(migrations()):
        raise RuntimeError(
            f"{db} has schema {version}; this scrap knows {len(migrations())}"
        )
    return version


def migrate(db: Path) -> None:
    """Apply the missing migrations, one process at a time (flock on db.lock). A
    migration's Python step (AFTER) runs in its transaction, after its script."""
    with open(f"{db}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        version = schema_version(db)
        with closing(connect(db)) as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            for n, sql in enumerate(migrations()[version:], start=version + 1):
                try:
                    conn.executescript(f"BEGIN IMMEDIATE;\n{sql}")
                    if n in AFTER:
                        AFTER[n](conn)
                    conn.execute(f"PRAGMA user_version = {n}")
                    conn.execute("COMMIT")
                except BaseException:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise


AFTER = {
    3: index_all, 4: index_all, 5: move_todo_fields, 6: add_snooze, 7: add_tasks,
    8: add_meta_revs,
    9: add_enrich,
    10: fix_tag_paths,
    11: add_related_reason,
}  # fmt: skip
