"""edit_meta's fields are only media_type, status, due and priority: any
other name is refused, saving nothing, never stored as a meaningless field (#386)."""

import pytest

from scrap.store import Store
from test_edit_meta_todo import old_json_revision, todo, values
from test_mcp import human, ok, refused

ALLOWED = "only media_type, status, due, priority"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def unchanged(store, key):
    """The todo as todo() made it: open, no todo values, no stray field, no revision."""
    page = store.page(key)
    assert page["fields"].get("status") == "open"
    assert "snoozd_until" not in page["fields"]
    assert values(store, key) == (None, None)
    assert ok(store, "revisions", page=key)["meta"] == []


def test_an_unknown_field_is_refused_naming_the_allowed_ones(store):
    key = todo(store)
    error = refused(
        store, "edit_meta", pages=[key],
        fields={"status": "done", "snoozd_until": "2099-01-02"},
    )  # fmt: skip
    assert "'snoozd_until' cannot be set here" in error and ALLOWED in error
    unchanged(store, key)  # not even the status given beside it


def test_an_unknown_field_is_refused_in_a_dry_run(store):
    key = todo(store)
    error = refused(
        store, "edit_meta", pages=[key], fields={"colour": "red"}, dry_run=True
    )
    assert ALLOWED in error
    unchanged(store, key)


def test_an_unknown_field_is_refused_in_a_query_batch(store):
    keys = [todo(store, f"Late {n}", tags=["late"]) for n in range(2)]
    error = refused(
        store, "edit_meta", query="tag:late", add_tags=["x"], fields={"extra": None}
    )
    assert ALLOWED in error
    for key in keys:
        unchanged(store, key)
        assert store.page(key)["tags"] == ["late"]


def test_a_revert_still_undoes_an_old_free_form_field(store):
    # before #386 edit_meta set any name: revert takes one it set off again
    key = human(store, "A note")["slug"]
    rid = old_json_revision(store, key, {"extra": "y"}, {}, {"extra": "y"})
    ok(store, "revert", revision=rid)
    assert "extra" not in store.page(key)["fields"]


def test_a_revert_gives_back_an_old_free_form_field_taken_off(store):
    key = human(store, "A note")["slug"]
    rid = old_json_revision(store, key, {}, {"extra": "y"}, {})
    ok(store, "revert", revision=rid)
    assert store.page(key)["fields"]["extra"] == "y"
