"""migrations/baseline.sql builds the frozen schema, and the baseline plus the later
migrations is the frozen head (#267, ADR 0037). Kept in CI permanently: a migration PR
that does not refreeze fails here (see scrap.store.baseline)."""

import json
import sqlite3
from contextlib import closing

from scrap.store import baseline
from scrap.store.baseline import BASELINE_FILE, SNAPSHOT_FILE, structure
from scrap.store.db import BASELINE, connect, latest, migrate, migrations

REGEN = "review the schema diff, then: uv run python -m scrap.store.baseline --snapshot"


def head_db(tmp_path):
    """A store made by the real code: the baseline, then every migration after it."""
    db = tmp_path / "head.db"
    migrate(db)
    return db


def baseline_db(tmp_path, sql=None, name="base"):
    """The baseline script alone (or an edited copy), at the baseline's version."""
    db = tmp_path / f"{name}.db"
    with closing(connect(db)) as conn:
        conn.executescript(
            "BEGIN;\n" + (sql or BASELINE_FILE.read_text()) + "\nCOMMIT;"
        )
        conn.execute(f"PRAGMA user_version = {BASELINE}")
    return db


def struct(db):
    with closing(connect(db)) as conn:
        return structure(conn)


def test_baseline_file_is_what_the_generator_writes():
    assert BASELINE_FILE.read_text() == baseline.generate(), REGEN
    assert f"version {BASELINE}." in BASELINE_FILE.read_text().splitlines()[0]


def test_a_store_made_from_the_baseline_is_the_frozen_snapshot(tmp_path):
    frozen = json.loads(SNAPSHOT_FILE.read_text())
    assert frozen["user_version"] == BASELINE
    assert frozen["rows"]["queue_state"], "the queue_state seed row"
    assert struct(baseline_db(tmp_path)) == frozen, REGEN


def test_baseline_plus_later_migrations_is_the_frozen_head(tmp_path):
    """A migration added without reviewing its schema diff and refreezing fails here."""
    frozen = json.loads(SNAPSHOT_FILE.parent.joinpath("schema_head.json").read_text())
    assert frozen["user_version"] == latest()
    assert struct(head_db(tmp_path)) == frozen, REGEN


def test_the_runner_makes_the_same_database_as_the_baseline_script(tmp_path):
    made, script = struct(head_db(tmp_path)), struct(baseline_db(tmp_path))
    if not migrations():
        assert made == script
    else:  # later migrations only add to the baseline's version
        assert made["user_version"] == latest() > script["user_version"]


def test_the_comparison_sees_one_column_of_drift(tmp_path):
    """The equivalence test is only worth having if it fails on a small drift."""
    sql = BASELINE_FILE.read_text()
    drifted = sql.replace("size        INTEGER NOT NULL,", "size        INTEGER,", 1)
    assert drifted != sql
    base, chain = struct(baseline_db(tmp_path, drifted)), struct(head_db(tmp_path))
    assert base["objects"] != chain["objects"]
    assert base["tables"] != chain["tables"]
    extra = sql.replace(
        "mime        TEXT NOT NULL,", "mime        TEXT NOT NULL, extra TEXT,", 1
    )
    assert (
        struct(baseline_db(tmp_path, extra, name="extra"))["tables"] != chain["tables"]
    )


def test_quotes_and_whitespace_are_normalised():
    assert baseline._norm('CREATE TABLE "enrich_job" (\n  id  INTEGER)') == (
        baseline._norm("CREATE TABLE enrich_job (\nid INTEGER)")
    )


def test_full_text_search_works_on_the_baseline(tmp_path):
    db = baseline_db(tmp_path)
    with closing(connect(db)) as conn:
        conn.execute(
            "INSERT INTO page (id, slug, title, created_at, updated_at)"
            " VALUES ('p1', 'p1', 'Pelican', 't', 't')"
        )
        conn.execute(
            "INSERT INTO chunk (page_id, ord, text, title)"
            " VALUES ('p1', 0, 'pelicans fish', 'Pelican')"
        )
        hit = conn.execute(
            "SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH 'pelican'"
        )
        assert hit.fetchall()
        conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('integrity-check')")
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    sqlite3.connect(db).close()
