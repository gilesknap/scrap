"""migrations/baseline.sql builds the same database as the whole migration chain, and
matches the frozen snapshot (#267). Kept in CI permanently: a migration PR that
doesn't regenerate the baseline fails here (see scrap.store.baseline)."""

import json
import re
import sqlite3
from contextlib import closing

from scrap.store import baseline
from scrap.store.baseline import BASELINE_FILE, SNAPSHOT_FILE, structure
from scrap.store.db import connect, migrate, migrations

REGEN = "regenerate with: uv run python -m scrap.store.baseline && ... --snapshot"


def chain_db(tmp_path):
    db = tmp_path / "chain.db"
    migrate(db)
    return db


def baseline_db(tmp_path, sql=None, version=None, name="base"):
    db = tmp_path / f"{name}.db"
    with closing(connect(db)) as conn:
        conn.executescript(
            "BEGIN;\n" + (sql or BASELINE_FILE.read_text()) + "\nCOMMIT;"
        )
        header = re.search(r"version (\d+)", BASELINE_FILE.read_text())
        assert header
        conn.execute(f"PRAGMA user_version = {version or int(header[1])}")
    return db


def struct(db):
    with closing(connect(db)) as conn:
        return structure(conn)


def test_baseline_file_is_what_the_generator_writes():
    assert BASELINE_FILE.read_text() == baseline.generate(), REGEN


def test_baseline_matches_the_chain(tmp_path):
    chain, base = struct(chain_db(tmp_path)), struct(baseline_db(tmp_path))
    assert chain["user_version"] == base["user_version"] == len(migrations()), REGEN
    assert chain["rows"] == base["rows"]
    assert chain["rows"]["queue_state"], "the queue_state seed row"
    for key in ("objects", "tables", "indexes"):
        assert chain[key] == base[key], (key, REGEN)


def test_baseline_matches_the_frozen_snapshot(tmp_path):
    frozen = json.loads(SNAPSHOT_FILE.read_text())
    assert struct(baseline_db(tmp_path)) == frozen, REGEN


def test_the_comparison_sees_one_column_of_drift(tmp_path):
    """The equivalence test is only worth having if it fails on a small drift."""
    sql = BASELINE_FILE.read_text()
    drifted = sql.replace("size        INTEGER NOT NULL,", "size        INTEGER,", 1)
    assert drifted != sql
    base, chain = struct(baseline_db(tmp_path, drifted)), struct(chain_db(tmp_path))
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
