"""edit_meta sets a todo's due and priority (page_todo) on any page, the
user's own too, as a metadata revision that revert undoes (#385)."""

import json
from contextlib import closing

import pytest

from scrap.store import Store, connect, meta
from test_mcp import human, ok, refused

SOON, LATER = "2099-01-02", "2099-03-04"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def todo(store, title="Buy milk", **extra):
    """A todo the user made in the PWA (no metadata revision yet)."""
    return human(store, title, kind="todo", **extra)["slug"]


def values(store, key):
    page = store.page(key)
    return page["due"], page["priority"]


def age(store):
    """Make every metadata revision look old: the next change is one of its own."""
    with closing(connect(store.db)) as conn:
        conn.execute("UPDATE page_meta_rev SET created_at = '2020-01-01T00:00:00.000Z'")


def test_edit_meta_sets_and_clears_each_value_on_a_users_todo(store):
    key = todo(store)
    out = ok(store, "edit_meta", pages=[key], fields={"due": SOON, "priority": "high"})
    row = out["pages"][0]
    assert row["changed"] and row["revision"]
    assert row["fields_added"] == {"due": SOON, "priority": "high"}
    assert row["fields_was"] == {}
    assert values(store, key) == (SOON, "high")
    page = store.page(key)
    assert not {"due", "priority"} & page["fields"].keys()
    age(store)
    cleared = ok(store, "edit_meta", pages=[key], fields={
        "due": None, "priority": None,
    })["pages"][0]  # fmt: skip
    assert cleared["fields_was"] == {"due": SOON, "priority": "high"}
    assert values(store, key) == (None, None)


def test_snoozed_until_is_no_field_now(store):
    # Snooze was retired (28 Oct 2026): edit_meta refuses it as any other name
    key = todo(store)
    error = refused(store, "edit_meta", pages=[key], fields={"snoozed_until": LATER})
    assert "'snoozed_until' cannot be set here" in error
    assert "snoozed_until" not in store.page(key)


def test_one_value_changes_and_the_others_stay(store):
    key = todo(store, due=SOON, priority="low")
    row = ok(store, "edit_meta", pages=[key], fields={"priority": "medium"})["pages"][0]
    assert row["fields_added"] == {"priority": "medium"}
    assert row["fields_was"] == {"priority": "low"}
    assert values(store, key) == (SOON, "medium")


def test_bad_values_are_refused_and_save_nothing(store):
    key = todo(store, due=SOON)
    for fields, error in (
        ({"due": "next week"}, "due must be a date"),
        ({"due": "2099-02-30"}, "due must be a date"),
        ({"due": 5}, "due must be a date"),
        ({"priority": "urgent"}, "priority must be one of"),
        ({"priority": "high", "due": "x"}, "due must be a date"),
    ):
        assert error in refused(store, "edit_meta", pages=[key], fields=fields)
    assert values(store, key) == (SOON, None)


def test_refused_on_a_page_that_is_not_a_todo_already(store):
    note = human(store, "Just a note")["slug"]
    assert "is a todo's: make it one first" in refused(
        store, "edit_meta", pages=[note], fields={"due": SOON}
    )
    assert "earlier call" in refused(  # as status: not in the same call as the kind
        store, "edit_meta", pages=[note], kind="todo", fields={"priority": "low"}
    )
    assert store.page(note)["kind"] == "note"
    key = todo(store)  # all or nothing: the todo beside it is not changed either
    refused(store, "edit_meta", pages=[key, note], fields={"priority": "high"})
    assert values(store, key) == (None, None)


def test_a_dry_run_saves_nothing(store):
    key = todo(store, due=SOON)
    dry = ok(store, "edit_meta", pages=[key], fields={
        "due": LATER, "priority": "high",
    }, dry_run=True)["pages"][0]  # fmt: skip
    assert dry["revision"] is None and dry["changed"]
    assert dry["fields_added"] == {"due": LATER, "priority": "high"}
    assert dry["fields_was"] == {"due": SOON}
    assert values(store, key) == (SOON, None)
    assert ok(store, "revisions", page=key)["meta"] == []


def test_setting_what_it_has_already_is_no_revision(store):
    key = todo(store, priority="high")
    row = ok(store, "edit_meta", pages=[key], fields={"priority": "high"})["pages"][0]
    assert not row["changed"] and row["revision"] is None


def test_revert_undoes_a_change(store):
    key = todo(store, due=SOON)
    row = ok(store, "edit_meta", pages=[key], fields={
        "due": LATER, "priority": "high",
    })["pages"][0]  # fmt: skip
    back = ok(store, "revert", revision=row["revision"])
    assert back["revision"]
    assert values(store, key) == (SOON, None)
    ok(store, "revert", revision=back["revision"])  # the revert is undone in turn
    assert values(store, key) == (LATER, "high")


def test_revert_gives_back_a_cleared_value(store):
    key = todo(store, due=SOON, priority="low")
    row = ok(store, "edit_meta", pages=[key], fields={"due": None})["pages"][0]
    assert values(store, key) == (None, "low")
    ok(store, "revert", revision=row["revision"])
    assert values(store, key) == (SOON, "low")


def test_revert_leaves_a_value_changed_since(store):
    key = todo(store)
    row = ok(store, "edit_meta", pages=[key], fields={"due": SOON})["pages"][0]
    page = store.page(key)  # the PWA moves it on since
    store.update_page(key, page["rev"], None, None, "me", todo={"due": LATER})
    ok(store, "revert", revision=row["revision"])
    assert values(store, key)[0] == LATER


def test_a_query_batch_puts_off_and_revert_batch_undoes_it(store):
    keys = [todo(store, f"Overdue {n}", tags=["late"]) for n in range(3)]
    dry = ok(
        store, "edit_meta", query="tag:late", fields={"due": LATER}, dry_run=True,
    )  # fmt: skip
    assert dry["changed"] == 3
    assert all(values(store, k)[0] is None for k in keys)
    out = ok(store, "edit_meta", query="tag:late", fields={"due": LATER})
    assert out["batch"] and out["changed"] == 3
    assert all(values(store, k)[0] == LATER for k in keys)
    undone = ok(store, "revert", batch=out["batch"])
    assert undone["batch"] and not undone["conflicts"]
    assert all(values(store, k) == (None, None) for k in keys)


def test_quick_changes_fold_into_one_revision(store):
    key = todo(store, due=SOON)
    one = ok(store, "edit_meta", pages=[key], fields={"due": LATER})["pages"][0]
    two = ok(store, "edit_meta", pages=[key], fields={"due": "2099-05-06"})["pages"][0]
    assert one["revision"] == two["revision"]
    rev = ok(store, "revisions", page=key)["meta"][0]
    assert rev["fields_added"] == {"due": "2099-05-06"}
    assert rev["fields_was"] == {"due": SOON}  # the first's
    ok(store, "revert", revision=rev["id"])
    assert values(store, key)[0] == SOON


def test_a_burst_that_sets_and_clears_a_value_leaves_no_revision(store):
    key = todo(store)
    ok(store, "edit_meta", pages=[key], fields={"due": LATER})
    out = ok(store, "edit_meta", pages=[key], fields={"due": None})
    assert out["pages"][0]["revision"] is None
    assert ok(store, "revisions", page=key)["meta"] == []
    assert values(store, key) == (None, None)


def test_a_burst_that_changes_then_clears_a_value_gives_it_back_on_revert(store):
    key = todo(store, priority="low")
    ok(store, "edit_meta", pages=[key], fields={"priority": "high"})
    ok(store, "edit_meta", pages=[key], fields={"priority": None})
    rev = ok(store, "revisions", page=key)["meta"][0]
    assert rev["fields_added"] == {} and rev["fields_was"] == {"priority": "low"}
    ok(store, "revert", revision=rev["id"])
    assert values(store, key)[1] == "low"


def test_a_todo_turned_note_in_the_same_call_keeps_its_value_hidden(store):
    # as status: the check is of the kind before, so a todo may be set and turned
    key = todo(store)
    ok(store, "edit_meta", pages=[key], kind="note", fields={"due": SOON})
    assert store.page(key)["due"] is None  # hidden on a note
    ok(store, "edit_meta", pages=[key], kind="todo")
    assert values(store, key)[0] == SOON


def test_reverting_a_burst_that_made_a_note_a_todo_and_cleared_gives_back(
    store, monkeypatch
):
    # the kind before the reverted revision is a note, but the value is page_todo's
    key = todo(store, priority="low")
    ok(store, "edit_meta", pages=[key], kind="note")
    age(store)
    # simulate a legacy row: a revision folded before #411 (which now keeps a field
    # edit apart from a kind change), still in a store made by an older scrap
    monkeypatch.setattr(meta, "_touched", lambda *_: frozenset())
    ok(store, "edit_meta", pages=[key], kind="todo")
    ok(store, "edit_meta", pages=[key], fields={"priority": None})
    monkeypatch.undo()
    rev = ok(store, "revisions", page=key)["meta"][0]
    assert (rev["kind_before"], rev["kind_after"]) == ("note", "todo")
    ok(store, "revert", revision=rev["id"])
    page = store.page(key)
    assert page["kind"] == "note" and "priority" not in page["fields"]
    with closing(connect(store.db)) as conn:
        row = conn.execute(
            "SELECT priority FROM page_todo WHERE page_id = ?", (page["id"],)
        )
        assert row.fetchone()[0] == "low"  # hidden on the note, in page_todo
    ok(store, "edit_meta", pages=[key], kind="todo")
    assert values(store, key)[1] == "low"


def old_json_revision(store, key, added, was, stored):
    """A revision edit_meta made before #385, when these names were free-form fields
    (in page.fields, on any kind): the page's fields as it left them, and the row."""
    page_id = store.page(key)["id"]
    with closing(connect(store.db)) as conn:
        for name, value in stored.items():
            conn.execute(
                "UPDATE page SET fields = json_set(fields, ?, ?) WHERE id = ?",
                (f"$.{name}", value, page_id),
            )
        kind = conn.execute("SELECT kind FROM page WHERE id = ?", (page_id,))
        kind = kind.fetchone()[0]
        cur = conn.execute(
            "INSERT INTO page_meta_rev (page_id, author, source, kind_before,"
            " kind_after, fixed_before, fixed_after, tags_before, tags_after,"
            " fields_added, fields_was, created_at, updated_at) VALUES"
            " (?, 'me', 'mcp', ?, ?, 0, 0, '[]', '[]', ?, ?, ?, ?)",
            (page_id, kind, kind, json.dumps(added), json.dumps(was),
             "2020-01-01T00:00:00.000Z", "2020-01-01T00:00:00.000Z"),
        )  # fmt: skip
        conn.commit()
        return cur.lastrowid


def test_reverting_an_old_free_form_due_on_a_note_takes_it_off(store):
    key = human(store, "A note")["slug"]
    rid = old_json_revision(store, key, {"due": "someday"}, {}, {"due": "someday"})
    ok(store, "revert", revision=rid)
    assert "due" not in store.page(key)["fields"]


def test_reverting_an_old_free_form_due_both_hold_acts_on_page_todo(store):
    key = todo(store, due=SOON)
    rid = old_json_revision(store, key, {"due": SOON}, {}, {"due": SOON})
    ok(store, "revert", revision=rid)
    assert values(store, key)[0] is None  # page_todo wins a tie
    assert store.page(key)["fields"]["due"] == SOON  # left aside


def test_reverting_an_old_free_form_due_only_fields_hold_takes_it_off(store):
    key = todo(store, due=LATER)
    rid = old_json_revision(store, key, {"due": SOON}, {}, {"due": SOON})
    ok(store, "revert", revision=rid)
    assert "due" not in store.page(key)["fields"]
    assert values(store, key)[0] == LATER  # page_todo's, which it did not set


def test_a_revert_giving_back_a_value_page_todo_refuses_keeps_it_a_field(store):
    # before #385 edit_meta took a free-form priority "urgent" off this todo
    key = todo(store)
    rid = old_json_revision(store, key, {}, {"priority": "urgent"}, {})
    ok(store, "revert", revision=rid)
    assert store.page(key)["fields"]["priority"] == "urgent"
    assert values(store, key) == (None, None)


def test_a_media_type_burst_that_ends_cleared_gives_the_first_back_on_revert(store):
    # the fold drops a field the burst took off (any field, not only a todo's)
    key = human(store, "Dune", kind="consume")["slug"]
    ok(store, "edit_meta", pages=[key], fields={"media_type": "book"})
    age(store)
    ok(store, "edit_meta", pages=[key], fields={"media_type": "film"})
    ok(store, "edit_meta", pages=[key], fields={"media_type": None})
    rev = ok(store, "revisions", page=key)["meta"][0]
    assert "media_type" not in rev["fields_added"]
    assert rev["fields_was"]["media_type"] == "book"
    assert "media_type" not in store.page(key)["fields"]
    ok(store, "revert", revision=rev["id"])
    assert store.page(key)["fields"]["media_type"] == "book"


def stale(store, key, **kv):
    """A field of a todo value's name the page holds aside (an import's priority
    that page_todo could not hold, or an edit_meta's before #385)."""
    page_id = store.page(key)["id"]
    with closing(connect(store.db)) as conn:
        for name, value in kv.items():
            conn.execute(
                "UPDATE page SET fields = json_set(fields, ?, ?) WHERE id = ?",
                (f"$.{name}", value, page_id),
            )
        conn.commit()


def test_reverting_a_new_value_beside_a_stale_field_undoes_page_todos(store):
    key = todo(store)
    stale(store, key, priority="urgent")
    row = ok(store, "edit_meta", pages=[key], fields={"priority": "high"})["pages"][0]
    assert values(store, key)[1] == "high"
    ok(store, "revert", revision=row["revision"])
    assert values(store, key)[1] is None
    assert store.page(key)["fields"]["priority"] == "urgent"  # left aside


def test_reverting_a_changed_due_beside_a_stale_field_gives_back_page_todos(store):
    key = todo(store, due=SOON)
    stale(store, key, due="next week")
    row = ok(store, "edit_meta", pages=[key], fields={"due": LATER})["pages"][0]
    age(store)
    ok(store, "revert", revision=row["revision"])
    assert values(store, key)[0] == SOON
    assert store.page(key)["fields"]["due"] == "next week"


def test_none_acts_on_page_todo_only_leaving_a_stale_field(store):
    key = todo(store, priority="low")
    stale(store, key, priority="urgent")
    row = ok(store, "edit_meta", pages=[key], fields={"priority": None})["pages"][0]
    assert row["fields_was"] == {"priority": "low"}
    assert store.page(key)["fields"]["priority"] == "urgent"
    age(store)
    row = ok(store, "edit_meta", pages=[key], fields={"priority": None})["pages"][0]
    assert not row["changed"] and row["revision"] is None
    assert store.page(key)["fields"]["priority"] == "urgent"


def test_revert_batch_undoes_a_page_with_a_stale_field_too(store):
    a, b = todo(store, "a"), todo(store, "b")
    stale(store, b, due="whenever")
    out = ok(store, "edit_meta", pages=[a, b], fields={"due": LATER})
    ok(store, "revert", batch=out["batch"])
    assert values(store, a)[0] is None
    assert values(store, b)[0] is None
    assert store.page(b)["fields"]["due"] == "whenever"
