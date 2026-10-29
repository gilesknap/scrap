"""A scrap export read back by the import (#417): every page as it was (its id, slug,
title, text, kind, fields, todo values, the owner's tags, dates, who made it and its
files), nothing a model wrote in any page, and a second import adds nothing."""

import io
import json
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from scrap import importer
from scrap.export import export
from scrap.store import Store, connect, topics
from test_export import MODEL_TEXT, add, data, sql, store_pages  # noqa: F401
from test_mcp import ok


def pages(store: Store) -> dict[str, dict[str, Any]]:
    """Every page not in the trash, by id: what an import must bring back."""
    with closing(connect(store.db)) as conn:
        rows = conn.execute(
            "SELECT p.*, t.due, t.priority FROM page p"
            " LEFT JOIN page_todo t ON t.page_id = p.id WHERE p.deleted_at IS NULL"
        ).fetchall()
        out = {}
        for row in rows:
            tags = {
                r[0]
                for r in conn.execute(
                    "SELECT tag FROM tag WHERE page_id = ? AND tag NOT IN"
                    " (SELECT tag FROM model_tag WHERE page_id = ?)",
                    (row["id"], row["id"]),
                )
            }
            blobs = {
                r[0]
                for r in conn.execute(
                    "SELECT cb.sha256 FROM capture c JOIN capture_blob cb"
                    " ON cb.capture_id = c.id WHERE c.page_id = ?",
                    (row["id"],),
                )
            }
            out[row["id"]] = {
                "slug": row["slug"],
                "title": row["title"],
                "body": row["body"],
                "kind": row["kind"],
                "fields": json.loads(row["fields"]),
                "due": row["due"],
                "priority": row["priority"],
                "tags": tags,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "made_by": row["made_by"],
                "blobs": blobs,
            }
        return out


@pytest.fixture
def store_a(client, data, store_pages):  # noqa: F811
    """store_pages, plus a page Claude wrote, a topic page, and fields that need
    quoting."""
    store = Store(data)
    ok(
        store,
        "write",
        title="By Claude",
        body="Claude's [[sprint-board]] page",
        origin="o",
    )
    with closing(connect(store.db)) as conn:
        topics.create(
            conn, "A topic", "a-topic", "a-topic", "me", "2026-10-01T00:00:00Z"
        )
        conn.commit()
    ref = add(client, "Tricky fields\nbody")
    sql(data, "UPDATE page SET fields = ? WHERE id = ?",
        '{"status": "a: b", "title": "a field", "n": 3, "ok": true,'
        ' "x: y #z": 1, "on": "x", "Null": 2}', ref["page_id"])  # fmt: skip
    return store


def imported(src: Path, into: Store, **options: Any) -> importer.Done:
    source = importer.source(src)
    try:
        plan = importer.plan(source, into)
        return importer.run(into, source, plan, **options)
    finally:
        source.close()


def as_it_was(a: Store, b: Store, done: importer.Done) -> None:
    """b holds a's pages but the topic page (Claude makes topics again), byte for
    byte, each with the import's tag too; the page in a's trash is not there."""
    before, after = pages(a), pages(b)
    tag = importer.import_tag()
    topic = [i for i, p in before.items() if p["made_by"] == "topic"]
    assert len(topic) == 1  # not imported: Claude makes topics again
    del before[topic[0]]
    assert done.new == len(before) == 6 and done.skipped == 0
    for page in after.values():
        assert tag in page["tags"]
        page["tags"].discard(tag)
    assert after == before
    assert "binned-page" not in {p["slug"] for p in after.values()}


def test_an_export_imports_as_it_was(store_a, tmp_path):
    out = tmp_path / "md"
    export(store_a, out)
    b = Store(tmp_path / "b")
    as_it_was(store_a, b, imported(out, b))


def test_no_model_text_reaches_a_page(store_a, tmp_path):
    out = tmp_path / "md"
    export(store_a, out)
    b = Store(tmp_path / "b")
    imported(out, b)
    with closing(connect(b.db)) as conn:
        text = "\n".join(
            r[0] for r in conn.execute("SELECT title || body || fields FROM page")
        )
        captures = "\n".join(
            r[0] or "" for r in conn.execute("SELECT text FROM capture")
        )
        for table in ("model_tag", "enrichment", "derived", "writeup"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    for model_text in MODEL_TEXT:
        assert model_text not in text and model_text not in captures


def test_the_same_export_again_adds_nothing(store_a, tmp_path):
    out = tmp_path / "md"
    export(store_a, out)
    b = Store(tmp_path / "b")
    first = imported(out, b)
    again = imported(out, b)
    assert (again.new, again.skipped) == (0, first.new)
    # into the store it came from: every page is here already, by its id
    back = imported(out, store_a)
    assert (back.new, back.skipped) == (0, first.new)


def test_an_edited_file_comes_in_as_a_new_page(store_a, tmp_path):
    """Without an id, a file is known by its path and bytes: an edit is a new page
    (suffixed), never written over the one imported before."""
    out = tmp_path / "md"
    (out / "loose.md").parent.mkdir(parents=True)
    (out / "loose.md").write_text("Loose page\nfirst\n")
    b = Store(tmp_path / "b")
    assert imported(out, b).new == 1
    (out / "loose.md").write_text("Loose page\nsecond\n")
    assert imported(out, b).new == 1
    slugs = {p["slug"]: p["body"] for p in pages(b).values()}
    assert slugs == {"loose": "Loose page\nfirst", "loose-2": "Loose page\nsecond"}


def test_the_downloaded_zip_imports_too(client, store_a, tmp_path):
    r = client.get("/api/store/download")
    zipped = tmp_path / "export.zip"
    zipped.write_bytes(r.content)
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert any(n.startswith("_claude/") for n in zf.namelist())
    b = Store(tmp_path / "b")
    as_it_was(store_a, b, imported(zipped, b))
