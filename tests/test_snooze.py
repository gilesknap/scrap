"""Snooze: a todo hidden from what to do now until a day (migration 6)."""

from contextlib import closing
from datetime import date, timedelta

import pytest

from scrap.store import Store, connect, migrations, todo_columns
from test_mcp import ok, write

TODAY = date.today()
LATER = (TODAY + timedelta(days=3)).isoformat()
PAST = (TODAY - timedelta(days=1)).isoformat()


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def search(client, q):
    return [h["title"] for h in client.get("/api/search", params={"q": q}).json()]


def test_patch_snoozes_a_todo_and_is_snoozed_finds_it_until_then(client, note):
    ref = note("Snooze the fence", kind="todo", due=PAST)
    url = f"/api/pages/{ref['page_id']}"
    before = client.get(url).json()
    assert before["snoozed_until"] is None
    page = client.patch(url, json={"snoozed_until": LATER}).json()
    assert page["snoozed_until"] == LATER and page["due"] == PAST  # due kept
    assert (page["rev"], page["updated_at"]) == (before["rev"], before["updated_at"])
    listed = client.get("/api/pages", params={"kind": "todo"}).json()[0]
    assert listed["snoozed_until"] == LATER
    assert search(client, "kind:todo is:snoozed") == ["Snooze the fence"]
    assert search(client, "kind:todo -is:snoozed") == []
    assert search(client, "fence")[0] == "Snooze the fence"  # the hit carries it
    hit = client.get("/api/search", params={"q": "fence"}).json()[0]
    assert hit["snoozed_until"] == LATER
    # Its day come (or gone): back in what to do
    client.patch(url, json={"snoozed_until": TODAY.isoformat()})
    assert search(client, "kind:todo is:snoozed") == []
    assert (
        client.patch(url, json={"snoozed_until": None}).json()["snoozed_until"] is None
    )


def test_is_snoozed_finds_open_todos_only(client, note):
    """A done or cancelled todo's snooze hides nothing: is:snoozed skips it (#131)."""
    for title, status in [
        ("Nap open", None),
        ("Nap going", "in_progress"),
        ("Nap done", "done"),
        ("Nap dropped", "cancelled"),
    ]:
        ref = note(title, kind="todo", snoozed_until=LATER)
        if status:
            url = f"/api/pages/{ref['page_id']}"
            client.patch(url, json={"fields": {"status": status}})
    assert sorted(search(client, "kind:todo is:snoozed")) == ["Nap going", "Nap open"]
    assert sorted(search(client, "kind:todo -is:snoozed")) == [
        "Nap done",
        "Nap dropped",
    ]


@pytest.mark.parametrize("value", ["2026-02-30", "tomorrow", "2026-11-01T10:00", 3])
def test_a_bad_snooze_is_refused(client, note, value):
    ref = note("Bad", kind="todo")
    r = client.patch(f"/api/pages/{ref['page_id']}", json={"snoozed_until": value})
    assert r.status_code == 422


def test_snooze_is_for_todos_and_goes_with_a_capture(client, note):
    plain = note("Just a note")
    r = client.patch(f"/api/pages/{plain['page_id']}", json={"snoozed_until": LATER})
    assert r.status_code == 422
    made = note("Later thing", kind="todo", snoozed_until=LATER)
    assert client.get(f"/api/pages/{made['page_id']}").json()["snoozed_until"] == LATER


def test_export_and_import_carry_it_as_front_matter(client, note, tmp_path):
    from scrap.__main__ import main

    ref = note("Snoozed export", kind="todo", due=PAST, snoozed_until=LATER)
    text = client.get(f"/api/pages/{ref['page_id']}/download").text
    assert f'\ndue: "{PAST}"\nsnoozed_until: "{LATER}"\n' in text
    assert f'snoozed_until: "{LATER}"' in exported(tmp_path, main, ref["slug"])
    # Read back (an import's front matter), it is the todo's column again
    cols, rest = todo_columns("todo", {"status": "open", "snoozed_until": LATER})
    assert (cols["snoozed_until"], rest) == (LATER, {"status": "open"})


def exported(tmp_path, main, slug):
    main(["export", "--data-dir", str(tmp_path / "data"), str(tmp_path / "md")])
    return (tmp_path / "md" / f"{slug}.md").read_text()


def test_migration_6_is_additive_and_can_run_again(tmp_path):
    """An older scrap runs with user_version set back to 5: migrating again later finds
    the column there and keeps it (and what it holds)."""
    Store(tmp_path).migrate()
    db = tmp_path / "scrap.db"
    with closing(connect(db)) as conn:
        assert (
            conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations()) >= 6
        )
        conn.execute(
            "INSERT INTO page (id, slug, title, kind, fields, created_at, updated_at,"
            " snoozed_until) VALUES ('A', 'a', 'T', 'todo', '{}', 'x', 'x', ?)",
            (LATER,),
        )
        with pytest.raises(Exception, match="CHECK"):
            conn.execute("UPDATE page SET snoozed_until = '2026-02-30'")
        # An older scrap's own writes name their columns: the new one is left alone
        conn.execute(
            "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
            " created_at, updated_at, due, priority)"
            " VALUES ('B', 'b', 'T', '', 'todo', 1, '{}', 'x', 'x', NULL, 'low')"
        )
        conn.execute("PRAGMA user_version = 5")
    Store(tmp_path).migrate()
    with closing(connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
        rows = conn.execute("SELECT id, snoozed_until FROM page ORDER BY id")
        assert [tuple(r) for r in rows] == [("A", LATER), ("B", None)]


def test_mcp_writes_and_shows_it_and_todos_leaves_it_out(store):
    page = write(store, title="Snoozed by Claude", kind="todo", snoozed_until=LATER)
    write(store, title="Open by Claude", kind="todo")
    read = ok(store, "read", page=page["id"])
    assert read["page"]["snoozed_until"] == LATER
    to_do = "kind:todo -is:done -is:cancelled -is:snoozed"
    titles = [r["title"] for r in ok(store, "search", query=to_do)["results"]]
    assert "Open by Claude" in titles and "Snoozed by Claude" not in titles
    found = ok(store, "search", query="kind:todo is:snoozed")["results"]
    assert [(r["title"], r["snoozed_until"]) for r in found] == [
        ("Snoozed by Claude", LATER)
    ]
