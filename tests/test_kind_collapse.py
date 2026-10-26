"""Migration 14 (#298): kinds memory and reference become document."""

import sqlite3

import pytest

from scrap.store import Store, topics
from scrap.store.db import AFTER, connect, migrations
from scrap.store.indexing import index_page

STAMP = "2025-01-01T00:00:00.000Z"


def v13(data):
    """A store folder whose database is at schema 13, with pages of the old kinds."""
    data.mkdir()
    conn = connect(data / "scrap.db")
    for n, sql in enumerate(migrations()[:13], start=1):
        conn.executescript(f"BEGIN IMMEDIATE;\n{sql}")
        if n in AFTER:
            AFTER[n](conn)
        conn.execute(f"PRAGMA user_version = {n}")
        conn.execute("COMMIT")
    rows = [  # id, kind, kind_fixed, deleted_at, title
        ("MEM", "memory", 1, None, "Day out zebra"),
        ("REF", "reference", 1, None, "Plain entity zebra"),
        ("TOP", "reference", 1, None, "Topic zebra"),
        ("TMEM", "memory", 1, STAMP, "Trashed memory zebra"),
        ("TREF", "reference", 1, STAMP, "Trashed reference zebra"),
        ("LOOSE", "memory", 0, None, "Unfixed memory zebra"),
        ("NOTE", "note", 0, None, "A note zebra"),
        ("DOC", "document", 1, None, "A doc zebra"),
    ]
    for page_id, kind, fixed, deleted, title in rows:
        conn.execute(
            "INSERT INTO page (id, slug, title, kind, kind_fixed, created_at,"
            " updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (page_id, page_id.lower(), title, kind, fixed, STAMP, STAMP, deleted),
        )
        index_page(conn, page_id)
    conn.execute("INSERT INTO topic VALUES ('TOP', 'zebra', ?)", (STAMP,))
    conn.execute("INSERT INTO tag VALUES ('MEM', 'keep')")
    conn.execute("INSERT INTO tag VALUES ('REF', 'entity')")  # already there
    conn.execute(
        "INSERT INTO page_meta_rev (page_id, author, source, kind_before, kind_after,"
        " fixed_before, fixed_after, tags_before, tags_after, created_at, updated_at)"
        " VALUES ('MEM', 'me', 'web', 'memory', 'reference', 0, 1, '[]', '[]', ?, ?)",
        (STAMP, STAMP),
    )
    conn.close()
    return data


def kinds(store):
    with store.connect() as conn:
        return {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT id, kind, kind_fixed FROM page")}  # fmt: skip


def tags(store):
    with store.connect() as conn:
        out: dict[str, list[str]] = {}
        for page_id, tag in conn.execute("SELECT page_id, tag FROM tag ORDER BY tag"):
            out.setdefault(page_id, []).append(tag)
        return out


@pytest.fixture
def migrated(tmp_path):
    store = Store(v13(tmp_path / "data"))
    store.migrate()
    return store


def test_pages_become_documents_with_tags(migrated):
    assert kinds(migrated) == {
        "MEM": ("document", 1),
        "REF": ("document", 1),
        "TOP": ("document", 1),
        "TMEM": ("document", 1),
        "TREF": ("document", 1),
        "LOOSE": ("document", 0),
        "NOTE": ("note", 0),
        "DOC": ("document", 1),
    }
    assert tags(migrated) == {
        "MEM": ["keep", "memory"],
        "REF": ["entity"],
        "TMEM": ["memory"],
        "TREF": ["entity"],
        "LOOSE": ["memory"],
    }  # the topic, the note and the document have none
    with migrated.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 14
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert conn.execute("SELECT page_id FROM topic").fetchall()[0][0] == "TOP"
        assert conn.execute("SELECT count(*) FROM page_rev").fetchone()[0] == 0
        (rev,) = conn.execute(
            "SELECT kind_before, kind_after FROM page_meta_rev"
        ).fetchall()
        assert tuple(rev) == ("document", "document")


def test_search_finds_pages_and_their_new_tags(migrated):
    def found(query):
        return {r["slug"] for r in migrated.search(query, 20)}

    assert found("zebra") == {"mem", "ref", "top", "loose", "note", "doc"}
    assert found("kind:document zebra") == {"mem", "ref", "top", "loose", "doc"}
    assert found("tag:memory") == {"mem", "loose"}
    assert found("tag:entity") == {"ref"}
    assert found("memory") == {"mem", "loose"}  # the tag is indexed
    assert found("is:topic") == {"top"}
    assert found("kind:memory") == found("kind:reference") == set()
    with migrated.connect() as conn:
        assert [t["key"] for t in topics.every(conn)] == ["zebra"]


def test_migrating_again_changes_nothing(migrated):
    before = (kinds(migrated), tags(migrated))
    with migrated.connect() as conn:  # as if it had stopped at 13
        conn.execute("PRAGMA user_version = 13")
    migrated.migrate()
    assert (kinds(migrated), tags(migrated)) == before
    with migrated.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 14


def test_check_takes_only_the_five_kinds(migrated, tmp_path):
    with migrated.connect() as conn:
        (sql,) = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'page'"
        ).fetchone()
        assert "'memory'" not in sql and "'reference'" not in sql
        for kind in ("memory", "reference"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("UPDATE page SET kind = ? WHERE id = 'NOTE'", (kind,))
        for kind in ("note", "todo", "consume", "whiteboard", "document"):
            conn.execute("UPDATE page SET kind = ? WHERE id = 'NOTE'", (kind,))


def test_a_new_store_has_the_same_check(tmp_path):
    store = Store(tmp_path / "new")
    store.migrate()
    with store.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 14
        (sql,) = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'page'"
        ).fetchone()
        assert "'memory'" not in sql
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO page (id, slug, title, kind, created_at, updated_at)"
                " VALUES ('X', 'x', 'x', 'reference', 'a', 'a')"
            )
