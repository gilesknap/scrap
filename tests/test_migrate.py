"""The runner: a baseline (schema 18) and the migrations numbered after it (#267)."""

import re
import sqlite3
from contextlib import closing
from importlib.resources import files

import pytest

from scrap import store as store_mod
from scrap.store import Store, db
from scrap.store.db import BASELINE, connect, create_baseline, latest, migrate

LATER = "CREATE TABLE later (id INTEGER PRIMARY KEY, x TEXT);\n"


def version(path):
    with closing(connect(path)) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def schema(path):
    with closing(connect(path)) as conn:
        return conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall()


def baseline_store(tmp_path, name="s.db"):
    path = tmp_path / name
    with closing(connect(path)) as conn:
        create_baseline(conn)
    return path


def test_migration_file_numbers_are_their_position_after_the_baseline():
    names = sorted(
        p.name
        for p in (files("scrap") / "migrations").iterdir()
        if p.name[:1].isdigit()
    )
    assert len(names) == len(db.migrations())
    for i, name in enumerate(names):
        assert re.match(rf"{BASELINE + 1 + i:04d}_\w+\.sql$", name), name


def test_the_baseline_is_not_a_numbered_migration():
    assert (files("scrap") / "migrations" / "baseline.sql").is_file()
    assert BASELINE == 18
    assert all("Schema baseline" not in sql for sql in db.migrations())


def test_a_fresh_database_is_made_from_the_baseline(tmp_path):
    path = tmp_path / "fresh.db"
    migrate(path)
    assert version(path) == latest() >= BASELINE
    names = {name for _, name, _ in schema(path)}
    assert {"page", "page_todo", "page_trash_rev", "chunk_fts"} <= names
    migrate(path)  # again: nothing to do
    assert version(path) == latest()


def test_a_database_at_the_baseline_is_opened_unchanged(tmp_path):
    path = baseline_store(tmp_path)
    before = schema(path)
    migrate(path)
    assert (schema(path), version(path)) == (before, BASELINE)
    Store(tmp_path).migrate()  # the store's own entry point, a fresh data dir
    assert version(tmp_path / "scrap.db") == latest()


@pytest.mark.parametrize("old", [1, 10, 16, 17])
def test_a_database_below_the_baseline_is_refused_untouched(tmp_path, old):
    path = baseline_store(tmp_path)
    with closing(connect(path)) as conn:
        conn.execute(f"PRAGMA user_version = {old}")
    before = schema(path)
    with pytest.raises(RuntimeError) as raised:
        migrate(path)
    message = str(raised.value)
    assert f"schema {old}" in message
    assert "upgrade with scrap 0.16.x first (it migrates to schema 18)" in message
    assert "then use 0.17.0 or later" in message
    with pytest.raises(RuntimeError, match="0.16.x"):
        store_mod.schema_version(path)
    assert (schema(path), version(path)) == (before, old)


def test_a_database_newer_than_this_scrap_is_refused(tmp_path):
    path = baseline_store(tmp_path)
    with closing(connect(path)) as conn:
        conn.execute(f"PRAGMA user_version = {latest() + 1}")
    with pytest.raises(RuntimeError, match=f"schema {latest() + 1}"):
        migrate(path)


def test_tables_without_a_version_are_not_built_over(tmp_path):
    path = tmp_path / "odd.db"
    with closing(connect(path)) as conn:
        conn.execute("CREATE TABLE stray (x)")
    with pytest.raises(RuntimeError, match="no schema version"):
        migrate(path)
    assert [name for _, name, _ in schema(path)] == ["stray"]


def test_a_later_migration_applies_on_top_of_the_baseline(tmp_path, monkeypatch):
    first = baseline_store(tmp_path, "old.db")
    fresh = tmp_path / "fresh.db"
    monkeypatch.setattr(db, "migrations", lambda: [LATER])
    assert latest() == BASELINE + 1
    migrate(first)  # a store at 18 migrates to 19
    migrate(fresh)  # a fresh one is baseline then 19
    for path in (first, fresh):
        assert version(path) == BASELINE + 1
        assert ("table", "later") in {(t, n) for t, n, _ in schema(path)}
    migrate(first)  # again: not run twice
    assert version(first) == BASELINE + 1


def test_a_failing_migration_rolls_back_and_leaves_the_version(tmp_path, monkeypatch):
    path = baseline_store(tmp_path)
    before = schema(path)
    monkeypatch.setattr(db, "migrations", lambda: [LATER + "CREATE TABLE later (x);"])
    with pytest.raises(sqlite3.OperationalError):
        migrate(path)
    assert (schema(path), version(path)) == (before, BASELINE)
