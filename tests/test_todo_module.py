"""store/todo.py: reading and writing a page's todo values, and SQL fragments."""

import sqlite3
from contextlib import closing

import pytest

from scrap.store import Store, connect, todo


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def test_col_and_cols_name_the_values():
    assert todo.col("due") == "(SELECT due FROM page_todo WHERE page_id = p.id)"
    assert "page_id = x.id" in todo.col("priority", "x")
    assert todo.cols("q").endswith(" AS priority")
    with pytest.raises(ValueError):
        todo.col("title")


def test_write_merges_over_what_the_page_has(store):
    with closing(connect(store.db)) as conn:
        conn.execute(
            "INSERT INTO page (id, slug, title, kind, fields, created_at, updated_at)"
            " VALUES ('A', 'a', 'T', 'todo', '{}', 'x', 'x')"
        )
        assert todo.read(conn, "A") == dict.fromkeys(todo.NAMES)
        todo.write(conn, "A", {"due": "2026-11-01", "priority": "low"})
        todo.write(conn, "A", {"priority": None})
        assert todo.read(conn, "A") == {"due": "2026-11-01", "priority": None}
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            todo.write(conn, "A", {"due": "2026-02-30"})
        with pytest.raises(ValueError):
            todo.write(conn, "A", {"title": "x"})
        assert todo.read(conn, "nope") == dict.fromkeys(todo.NAMES)
