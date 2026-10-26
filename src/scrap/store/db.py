"""The database: connections, transactions, schema migrations."""

import fcntl
import hashlib
import json
import logging
import sqlite3
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import closing, contextmanager
from importlib.resources import files as package_files
from pathlib import Path
from typing import Any

from ..markdown import wiki_targets
from ..public import public_origins
from . import grouping
from .fixes import (
    add_enrich,
    add_fields_was,
    add_made_by,
    add_meta_revs,
    add_related_reason,
    add_snooze,
    add_tasks,
    add_topics,
    add_writeups,
    collapse_kinds,
    fix_tag_paths,
    move_todo_fields,
)
from .indexing import index_all


def migrations() -> list[str]:
    """The numbered migration scripts, in order: script N sets user_version N."""
    folder = package_files("scrap") / "migrations"
    scripts = sorted((p for p in folder.iterdir() if p.name.endswith(".sql")), key=str)
    return [p.read_text() for p in scripts]


log = logging.getLogger(__name__)
# wiki_links' parses, by the origins and the text's digest, not the text: a check
# reads every page's text, and most are as they were last time. The least recently
# used go first. A check reads every page with links in turn, so a store with more
# such pages than this re-parses them all each time (LRU in a loop): the cliff sits
# well above a personal store's size, at little memory (short JSON arrays).
_PARSED: OrderedDict[tuple[tuple[str, ...], bytes], str] = OrderedDict()
_MAX_PARSED = 16384
_failed = False  # a parse has failed (logged once)


def wiki_links(text: str | None) -> str:
    """SQL wiki_links(text): the targets of a text's page links as a JSON array
    (markdown.wiki_targets: [[slug]], and /p/<slug> as a path or on any of
    $SCRAP_PUBLIC_URL's origins), for links, backlinks and the store health checks
    (store.health). A text the parser fails on has none ("[]"): a health check must
    never fail a search; the first such failure is logged."""
    global _failed
    if not text or ("[[" not in text and "/p/" not in text):  # most: nothing to parse
        return "[]"
    origins = public_origins()
    key = (origins, hashlib.sha256(text.encode()).digest())
    if (found := _PARSED.get(key)) is not None:
        _PARSED.move_to_end(key)
        return found
    try:
        found = json.dumps(wiki_targets(text, origins))
    except Exception:  # noqa: BLE001  any parser failure: no links, logged once
        if not _failed:
            _failed = True
            log.exception(
                "wiki_links: can't parse a page's text (%d characters, sha256 %s);"
                " it counts as having no links",
                len(text), key[1].hex()[:12],
            )  # fmt: skip
        return "[]"
    _PARSED[key] = found
    if len(_PARSED) > _MAX_PARSED:
        _PARSED.popitem(last=False)
    return found


def connect(db: Path | str) -> sqlite3.Connection:
    """Open the database in autocommit mode with the per-connection pragmas, and the
    SQL function wiki_links."""
    conn = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.create_function("wiki_links", 1, wiki_links, deterministic=True)
    for name, (args, fn) in grouping.FUNCTIONS.items():
        conn.create_function(name, args, fn, deterministic=True)
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
    12: add_writeups,
    13: add_topics,
    14: collapse_kinds,
    15: add_fields_was,
    16: add_made_by,
}  # fmt: skip
