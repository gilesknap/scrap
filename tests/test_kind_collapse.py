"""The kind check (#298): page.kind takes only the five kinds, memory and reference
being gone. (The migration that collapsed them is in the baseline since #267.)"""

import sqlite3

import pytest

from scrap.store import Store
from scrap.store.db import latest

STAMP = "2025-01-01T00:00:00.000Z"


def test_a_new_store_takes_only_the_five_kinds(tmp_path):
    store = Store(tmp_path / "new")
    store.migrate()
    with store.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == latest()
        (sql,) = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'page'"
        ).fetchone()
        assert "'memory'" not in sql and "'reference'" not in sql
        for kind in ("memory", "reference"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO page (id, slug, title, kind, created_at, updated_at)"
                    " VALUES ('X', 'x', 'x', ?, ?, ?)",
                    (kind, STAMP, STAMP),
                )
        for n, kind in enumerate(("note", "todo", "consume", "whiteboard", "document")):
            conn.execute(
                "INSERT INTO page (id, slug, title, kind, created_at, updated_at)"
                " VALUES (?, ?, 'x', ?, ?, ?)",
                (f"K{n}", f"k{n}", kind, STAMP, STAMP),
            )
