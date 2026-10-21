"""Task lists drive a todo: boxes counted, a note with boxes filed as a todo, and its
status following them (store.Store._body)."""

from contextlib import closing

import pytest

from scrap.markdown import tasks
from scrap.store import Store, connect, migrations
from test_mcp import ok

BOXES = "Packing\n\n- [ ] socks\n- [x] passport\n- [ ] charger"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def test_boxes_are_counted_as_the_pwa_draws_them():
    assert tasks(BOXES) == (1, 3)
    text = "```\n- [ ] in a fence\n```\n\n    - [x] indented code\n\n# [ ] a heading\n"
    assert tasks(text) == (0, 0)
    assert tasks(
        "> - [x] quoted\n1. [ ] numbered\n   * [X] nested\n- [y] no\n- [x](u)"
    ) == (
        2,
        3,
    )


def test_a_note_with_boxes_becomes_a_todo_unless_its_kind_was_chosen(client, note):
    ref = note(BOXES)
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert (page["kind"], page["kind_fixed"], page["fields"]) == (
        "todo",
        0,
        {"status": "open"},
    )
    assert page["tasks"] == {"done": 1, "total": 3}
    chosen = note(BOXES, kind="note")  # Note picked in the composer: kept
    assert client.get(f"/api/pages/{chosen['page_id']}").json()["kind"] == "note"
    read = note(BOXES, kind="consume")  # never a Read, Board or Doc
    assert client.get(f"/api/pages/{read['page_id']}").json()["kind"] == "consume"
    # Made a note by hand after: it stays one, boxes or not
    url = f"/api/pages/{ref['page_id']}"
    client.patch(url, json={"kind": "note"}).raise_for_status()
    client.patch(
        url, json={"base_rev": 1, "body": BOXES + "\n- [ ] more"}
    ).raise_for_status()
    assert client.get(url).json()["kind"] == "note"


def test_the_status_follows_the_boxes_both_ways(client, note):
    ref = note(BOXES)
    url = f"/api/pages/{ref['page_id']}"

    def save(body):
        rev = client.get(url).json()["rev"]
        page = client.patch(url, json={"base_rev": rev, "body": body}).json()
        return page["fields"]["status"], page["tasks"]

    every = BOXES.replace("[ ]", "[x]")
    assert save(every) == ("done", {"done": 3, "total": 3})  # the last box: done
    assert save(BOXES) == ("open", {"done": 1, "total": 3})  # one unticked: open again
    # Done by hand ticks no box, and other edits leave it done
    client.patch(url, json={"fields": {"status": "done"}})
    assert client.get(url).json()["body"] == BOXES
    assert save(BOXES + "\n\nA line more") == ("done", {"done": 1, "total": 3})
    # Cancelled: never changed by its boxes
    client.patch(url, json={"fields": {"status": "cancelled"}})
    assert save(every)[0] == "cancelled"
    assert save(BOXES)[0] == "cancelled"


def test_rows_search_mcp_and_export_carry_the_counts(client, note, tmp_path):
    from scrap.__main__ import main

    ref = note(BOXES)
    row = client.get("/api/pages").json()[0]
    assert row["tasks"] == {"done": 1, "total": 3}
    hit = client.get("/api/search", params={"q": "passport"}).json()[0]
    assert hit["tasks"] == {"done": 1, "total": 3}
    text = client.get(f"/api/pages/{ref['page_id']}/download").text
    assert '\ntasks: {"done": 1, "total": 3}\n' in text
    plain = note("No boxes here")
    assert client.get(f"/api/pages/{plain['page_id']}").json()["tasks"] == {
        "done": 0,
        "total": 0,
    }
    main(["export", "--data-dir", str(tmp_path / "data"), str(tmp_path / "md")])
    assert "\ntasks:" not in (tmp_path / "md" / f"{plain['slug']}.md").read_text()


def test_mcp_read_and_append_count_them(store):
    page = ok(
        store, "write", title="Plan", body="- [ ] a\n- [ ] b", origin="o", kind="todo"
    )
    assert ok(store, "read", page=page["id"])["page"]["tasks"] == {
        "done": 0,
        "total": 2,
    }
    ok(store, "write", title="", body="- [x] c", origin="", append_to=page["id"])
    read = ok(store, "read", page=page["id"])["page"]
    assert read["tasks"] == {"done": 1, "total": 3}


def test_migration_7_counts_again_what_an_older_scrap_left(tmp_path):
    Store(tmp_path).migrate()
    db = tmp_path / "scrap.db"
    with closing(connect(db)) as conn:
        conn.execute(
            "INSERT INTO page (id, slug, title, body, kind, fields, created_at,"
            " updated_at) VALUES ('A', 'a', 'T', ?, 'note', '{}', 'x', 'x')",
            (BOXES,),
        )  # as an older scrap writes it: no counts
        conn.execute("PRAGMA user_version = 6")
    Store(tmp_path).migrate()
    with closing(connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
        row = conn.execute("SELECT task_done, task_total FROM page WHERE id = 'A'")
        assert tuple(row.fetchone()) == (1, 3)


def test_migration_7_upgrades_a_version_6_scrap(tmp_path, monkeypatch):
    import scrap.store as store_module

    every = migrations()
    monkeypatch.setattr(store_module, "migrations", lambda: every[:6])
    Store(tmp_path).migrate()  # a scrap as version 6 made it: no count columns
    db = tmp_path / "scrap.db"
    with closing(connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        columns = {row[1] for row in conn.execute("PRAGMA table_info(page)")}
        assert not {"task_done", "task_total"} & columns
        conn.execute(
            "INSERT INTO page (id, slug, title, body, kind, fields, created_at,"
            " updated_at) VALUES ('A', 'a', 'T', ?, 'note', '{}', 'x', 'x'),"
            " ('B', 'b', 'U', 'no boxes', 'note', '{}', 'x', 'x')",
            (BOXES,),
        )
    monkeypatch.setattr(store_module, "migrations", lambda: every)
    Store(tmp_path).migrate()
    with closing(connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
        rows = conn.execute(
            "SELECT id, task_done, task_total, kind FROM page ORDER BY id"
        )
        # counted, and nothing refiled: migrating changes no page's kind or status
        assert [tuple(r) for r in rows] == [("A", 1, 3, "note"), ("B", 0, 0, "note")]
