"""The schema baseline: migrations/baseline.sql, the schema every scrap 1.0 database
starts from (#267, ADR 0037).

The file is generated, never edited by hand: it is the stored SQL of every object in a
database, plus its seed rows and the full-text index rebuild. Its schema version is
``db.BASELINE``; migrations numbered after it are applied on top, by merge order.
tests/test_baseline.py holds two frozen structures:

* tests/data/schema_baseline.json: the baseline alone. Changes only at a fold.
* tests/data/schema_head.json: the baseline plus every later migration. A new
  migration fails the test until you review its schema diff and refreeze::

    uv run python -m scrap.store.baseline --snapshot

Folding the migrations into the baseline (rare; when the live store is past them)::

    uv run python -m scrap.store.baseline --fold   # then bump db.BASELINE to the
                                                   # file's version, delete the folded
                                                   # scripts, and run --snapshot
    uv run python -m scrap.store.baseline --check  # exit 1 if the file was hand-edited
"""

import json
import re
import sqlite3
import sys
import tempfile
from contextlib import closing
from importlib.resources import files as package_files
from pathlib import Path

from .db import connect, create_baseline, migrate

BASELINE_FILE = Path(str(package_files("scrap") / "migrations" / "baseline.sql"))
DATA = Path(__file__).parents[3] / "tests" / "data"
SNAPSHOT_FILE = DATA / "schema_baseline.json"  # the baseline alone
HEAD_FILE = DATA / "schema_head.json"  # the baseline and every migration after it
# FTS5's own shadow tables are rebuilt by creating chunk_fts; they are not dumped.
_SHADOW_SUFFIXES = ("_data", "_idx", "_docsize", "_config", "_content")
_ORDER = {"table": 0, "index": 1, "trigger": 2, "view": 3}


def schema_objects(conn: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    """(type, name, tbl_name, sql) of every object to dump, tables then indexes then
    triggers, each in creation order. Skips SQLite's internal tables, automatic
    indexes (no SQL) and the shadow tables of virtual tables."""
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master"
        " WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
        " ORDER BY rowid"
    ).fetchall()
    virtual = {r[1] for r in rows if r[3].upper().startswith("CREATE VIRTUAL TABLE")}
    kept = [
        (r[0], r[1], r[2], r[3])
        for r in rows
        if not (
            r[0] == "table"
            and any(r[1] == v + s for v in virtual for s in _SHADOW_SUFFIXES)
        )
    ]
    return sorted(kept, key=lambda r: _ORDER[r[0]])  # sorted is stable


def seed_statements(conn: sqlite3.Connection) -> list[str]:
    """INSERTs for every row the chain leaves in a fresh database."""
    out = []
    for kind, name, _, _ in schema_objects(conn):
        if kind != "table" or name.endswith("_fts"):
            continue
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')]
        quoted = ", ".join(f'quote("{c}")' for c in cols)
        order = ", ".join(f'"{c}"' for c in cols)
        for row in conn.execute(f'SELECT {quoted} FROM "{name}" ORDER BY {order}'):
            out.append(
                f'INSERT INTO "{name}" ({", ".join(cols)}) VALUES ({", ".join(row)});'
            )
    return out


def _norm(sql: str) -> str:
    """SQL text without identifier quotes and with whitespace collapsed: a rebuilt
    table is stored as CREATE TABLE "enrich_job" on a live store, unquoted on a fresh
    one; the structure is the same."""
    return re.sub(r"\s+", " ", sql.replace('"', "")).strip()


def structure(conn: sqlite3.Connection) -> dict:
    """Everything that makes two databases the same schema: each object's normalised
    SQL, each table's columns and foreign keys, each index's columns, every table's
    rows (the seed) and the user_version. JSON-ready."""
    out: dict = {"user_version": conn.execute("PRAGMA user_version").fetchone()[0]}
    objects, tables, indexes, rows = {}, {}, {}, {}
    for kind, name, tbl, sql in schema_objects(conn):
        objects[name] = [kind, tbl, _norm(sql)]
        if kind == "table":
            xinfo = conn.execute(f'PRAGMA table_xinfo("{name}")')
            fks = conn.execute(f'PRAGMA foreign_key_list("{name}")')
            tables[name] = {
                "columns": [list(r) for r in xinfo],
                "foreign_keys": [list(r) for r in fks],
            }
            if not name.endswith("_fts"):
                rows[name] = [
                    list(r) for r in conn.execute(f'SELECT * FROM "{name}" ORDER BY 1')
                ]
        elif kind == "index":
            indexes[name] = [
                list(r) for r in conn.execute(f'PRAGMA index_xinfo("{name}")')
            ]
    out |= {"objects": objects, "tables": tables, "indexes": indexes, "rows": rows}
    return out


def snapshot_text(conn: sqlite3.Connection) -> str:
    return json.dumps(structure(conn), indent=1, sort_keys=True) + "\n"


def dump(conn: sqlite3.Connection) -> str:
    """The text of a baseline.sql that rebuilds this database's schema and seed rows,
    at its user_version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    parts = [
        f"-- Schema baseline, version {version}. GENERATED by"
        " `python -m scrap.store.baseline`: do not edit by hand.\n"
    ]
    parts += [f"{sql};\n" for _, _, _, sql in schema_objects(conn)]
    parts += [s + "\n" for s in seed_statements(conn)]
    parts.append("INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild');\n")
    return "\n".join(parts)


def generate(fold: bool = False) -> str:
    """The text of baseline.sql, from a database built by the real code: from the
    baseline alone (what the file must equal), or with fold=True also with every
    migration after it (the new baseline, when they are folded into it)."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "b.db"
        if fold:
            migrate(db)
        with closing(connect(db)) as conn:
            if not fold:
                create_baseline(conn)
            return dump(conn)


def snapshots() -> dict[Path, str]:
    """The frozen structures: the baseline's, and the head's (baseline plus every later
    migration), by file."""
    with tempfile.TemporaryDirectory() as tmp:
        base, head = Path(tmp) / "base.db", Path(tmp) / "head.db"
        with closing(connect(base)) as conn:
            create_baseline(conn)
            out = {SNAPSHOT_FILE: snapshot_text(conn)}
        migrate(head)
        with closing(connect(head)) as conn:
            out[HEAD_FILE] = snapshot_text(conn)
    return out


def main(argv: list[str]) -> int:
    if "--snapshot" in argv:  # freeze the structures for tests/test_baseline.py
        for path, text in snapshots().items():
            path.write_text(text)
        return 0
    if "--fold" in argv:  # the migrations folded in; then bump BASELINE, delete them
        BASELINE_FILE.write_text(generate(fold=True))
        return 0
    text = generate()
    if "--check" in argv:
        if BASELINE_FILE.read_text() == text:
            return 0
        print("baseline.sql is not what the generator writes: do not edit it by hand")
        return 1
    BASELINE_FILE.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
