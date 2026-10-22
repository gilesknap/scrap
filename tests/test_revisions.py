"""Kinds and tags edited over MCP (edit_meta, rename_tag), on any page, and the
metadata revisions that make every such edit visible and revertible."""

from contextlib import closing

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client

from scrap import mcp_server
from scrap.app import create_app
from scrap.store import Store, connect, migrations
from test_mcp import human, ok, refused, write


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def meta(store, key):
    return ok(store, "revisions", page=key)["meta"]


def age(store, revision: int, stamp="2020-01-01T00:00:00.000Z"):
    """Make a revision look as if it was made long ago (outside the window)."""
    with closing(connect(store.db)) as conn:
        conn.execute(
            "UPDATE page_meta_rev SET created_at = ? WHERE id = ?", (stamp, revision)
        )


def test_edit_meta_sets_the_kind_of_a_users_page(store):
    ref = human(store, "Whiteboard from the meeting")
    before = store.page(ref["page_id"])
    out = ok(store, "edit_meta", pages=[ref["slug"]], kind="board")
    assert out["changed"] == 1 and not out["dry_run"]
    row = out["pages"][0]
    assert (row["kind_before"], row["kind_after"]) == ("note", "whiteboard")
    assert row["revision"] and row["url"].endswith(f"/p/{ref['slug']}")
    after = store.page(ref["page_id"])
    assert after["kind"] == "whiteboard" and after["kind_fixed"] == 1
    # only metadata: the text, its revision and when it was last updated stay
    assert (after["title"], after["body"], after["rev"], after["updated_at"]) == (
        before["title"], before["body"], before["rev"], before["updated_at"],
    )  # fmt: skip


def test_edit_meta_adds_removes_and_sets_tags(store):
    ref = human(store, "Trip notes", tags=["travel", "a/b", "old"])
    out = ok(
        store, "edit_meta", pages=[ref["page_id"]], add_tags=["#Holiday", "travel"],
        remove_tags=["old", "a"],
    )  # fmt: skip
    row = out["pages"][0]
    assert row["tags_added"] == ["holiday"] and row["tags_removed"] == ["old"]
    assert store.page(ref["page_id"])["tags"] == ["a/b", "holiday", "travel"]
    assert ok(store, "search", query="tag:holiday")["results"][0]["slug"] == ref["slug"]
    ok(store, "edit_meta", pages=[ref["slug"]], set_tags=["x"])
    assert store.page(ref["page_id"])["tags"] == ["x"]
    ok(store, "edit_meta", pages=[ref["slug"]], set_tags=[])
    assert store.page(ref["page_id"])["tags"] == []


def test_an_edit_that_changes_nothing_is_no_revision(store):
    ref = human(store, "x", tags=["t"])
    out = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["t"], kind="note")
    assert out["changed"] == 0 and out["pages"][0]["revision"] is None
    assert meta(store, ref["slug"]) == []


def test_edit_meta_refuses_bad_requests(store):
    ref = human(store)
    for args, error in [
        ({"kind": "memo"}, "kind must be one of"),
        ({"kind": "memory"}, "kind must be one of"),
        ({}, "nothing to change"),
        ({"add_tags": ["a"], "set_tags": ["b"]}, "replace them all"),
        ({"add_tags": ["a"], "remove_tags": ["A"]}, "both added and removed"),
        ({"add_tags": ["x" * 65]}, "1 to 64 characters"),
    ]:
        assert error in refused(store, "edit_meta", pages=[ref["slug"]], **args)
    assert "not both" in refused(
        store, "edit_meta", pages=[ref["slug"]], query="x", kind="todo"
    )
    assert "not both" in refused(store, "edit_meta", kind="todo")
    assert store.page(ref["page_id"])["kind"] == "note"


def test_edit_meta_is_all_or_nothing(store):
    ref = human(store)
    error = refused(store, "edit_meta", pages=[ref["slug"], "nope"], kind="todo")
    assert "no such page" in error
    assert store.page(ref["page_id"])["kind"] == "note"
    assert meta(store, ref["slug"]) == []


def test_bulk_by_query_with_a_dry_run(store):
    refs = [human(store, f"Board {n}", tags=["meeting"]) for n in range(3)]
    other = human(store, "Shopping")
    dry = ok(store, "edit_meta", query="tag:meeting", kind="board", dry_run=True)
    assert dry["dry_run"] and dry["matched"] == 3 and dry["changed"] == 3
    assert {p["slug"] for p in dry["pages"]} == {r["slug"] for r in refs}
    assert all(p["revision"] is None for p in dry["pages"])
    assert {store.page(r["page_id"])["kind"] for r in refs} == {"note"}  # unsaved
    assert all(meta(store, r["slug"]) == [] for r in refs)
    out = ok(store, "edit_meta", query="tag:meeting", kind="board")
    assert out["changed"] == 3
    assert {store.page(r["page_id"])["kind"] for r in refs} == {"whiteboard"}
    assert store.page(other["page_id"])["kind"] == "note"
    error = refused(store, "edit_meta", query="tag:meeting", kind="doc", limit=2)
    assert "more than 2 pages" in error
    assert {store.page(r["page_id"])["kind"] for r in refs} == {"whiteboard"}


def test_bulk_by_slugs(store):
    refs = [human(store, f"Read {n}") for n in range(2)]
    slugs = [r["slug"] for r in refs]
    out = ok(store, "edit_meta", pages=[*slugs, slugs[0]], kind="read")
    assert out["matched"] == 2  # each page once
    assert {store.page(s)["kind"] for s in slugs} == {"consume"}
    assert store.page(slugs[0])["fields"]["status"] == "open"  # its kind's defaults


def test_rename_tag_renames_nested_tags_and_merges(store):
    a = human(store, "a", tags=["proj", "proj/x", "keep"])
    b = human(store, "b", tags=["project", "proj"])
    c = human(store, "c", tags=["projx"])
    dry = ok(store, "rename_tag", old="proj", new="project", dry_run=True)
    assert dry["changed"] == 2 and store.page(a["slug"])["tags"] != []
    assert sorted(store.page(a["slug"])["tags"]) == ["keep", "proj", "proj/x"]
    ok(store, "rename_tag", old="proj", new="Project")
    assert sorted(store.page(a["slug"])["tags"]) == ["keep", "project", "project/x"]
    assert store.page(b["slug"])["tags"] == ["project"]  # merged
    assert store.page(c["slug"])["tags"] == ["projx"]  # another tag
    assert "the old one" in refused(store, "rename_tag", old="a", new="A")
    rev = meta(store, b["slug"])[0]
    assert rev["tags_removed"] == ["proj"] and rev["tags_added"] == []


def test_revisions_record_actor_and_old_and_new_values(store):
    ref = human(store, "x", tags=["a"])
    ok(store, "edit_meta", pages=[ref["slug"]], kind="todo", add_tags=["b"])
    [rev] = meta(store, ref["slug"])
    assert (rev["author"], rev["source"], rev["reverts"]) == ("claude", "mcp", None)
    assert (rev["kind_before"], rev["kind_after"]) == ("note", "todo")
    assert (rev["tags_before"], rev["tags_after"]) == (["a"], ["a", "b"])
    assert rev["tags_added"] == ["b"] and rev["tags_removed"] == []


def test_quick_edits_coalesce_into_one_revision(store):
    ref = human(store, "x")
    one = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["a"])
    two = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["b"], kind="doc")
    assert one["pages"][0]["revision"] == two["pages"][0]["revision"]
    [rev] = meta(store, ref["slug"])
    assert (rev["kind_before"], rev["tags_before"]) == ("note", [])
    assert (rev["kind_after"], rev["tags_after"]) == ("document", ["a", "b"])
    assert rev["updated_at"] >= rev["created_at"]


def test_edits_outside_the_window_or_by_another_are_new_revisions(store):
    ref = human(store, "x")
    first = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["a"])
    age(store, first["pages"][0]["revision"])
    second = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["b"])
    assert second["pages"][0]["revision"] != first["pages"][0]["revision"]
    # the user, in the PWA, within the window of Claude's: a revision of their own
    store.update_page(ref["slug"], None, None, None, "giles@example.com", tags=["c"])
    revs = meta(store, ref["slug"])
    assert [(r["author"], r["source"]) for r in revs] == [
        ("giles@example.com", "web"), ("claude", "mcp"), ("claude", "mcp"),
    ]  # fmt: skip
    assert (revs[0]["tags_before"], revs[0]["tags_after"]) == (["a", "b"], ["c"])


def test_a_window_of_0_never_coalesces(store):
    store.window = 0
    ref = human(store, "x")
    for tag in "ab":
        store.edit_meta([ref["slug"]], "claude", "mcp", add=[tag])
    assert len(store.revisions(ref["slug"])["meta"]) == 2


def test_the_window_comes_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_REVISION_WINDOW", "60")
    assert Store(tmp_path).window == 60
    monkeypatch.setenv("SCRAP_REVISION_WINDOW", "soon")
    with pytest.raises(SystemExit, match="SCRAP_REVISION_WINDOW"):
        Store(tmp_path)


def test_a_change_made_elsewhere_between_is_not_folded_over(store):
    """Coalescing only extends a revision whose after is the page's state: a change
    nobody recorded between (ingest's tags) keeps the two apart."""
    ref = human(store, "x")
    first = store.edit_meta([ref["slug"]], "claude", "mcp", add=["a"])[0]
    with closing(connect(store.db)) as conn:
        conn.execute("INSERT INTO tag VALUES (?, 'by-ingest')", (ref["page_id"],))
    second = store.edit_meta([ref["slug"]], "claude", "mcp", add=["b"])[0]
    assert second["revision"] != first["revision"]


def test_revert_restores_the_state_before_and_is_a_revision(store):
    ref = human(store, "x", tags=["mine"])
    first = ok(store, "edit_meta", pages=[ref["slug"]], kind="board")["pages"][0]
    age(store, first["revision"])
    ok(store, "edit_meta", pages=[ref["slug"]], set_tags=["wrong"])
    dry = ok(store, "revert", revision=first["revision"], dry_run=True)
    assert dry["dry_run"] and dry["revision"] is None
    assert store.page(ref["slug"])["tags"] == ["wrong"]
    out = ok(store, "revert", revision=first["revision"])
    assert out["reverts"] == first["revision"] and out["revision"]
    assert (out["kind_after"], out["tags_after"]) == ("note", ["mine"])
    p = store.page(ref["slug"])
    assert (p["kind"], p["tags"], p["body"]) == ("note", ["mine"], "x")
    revs = meta(store, ref["slug"])
    assert len(revs) == 3 and revs[0]["reverts"] == first["revision"]
    # nothing is lost: reverting the revert puts back what it undid
    ok(store, "revert", revision=out["revision"])
    p = store.page(ref["slug"])
    assert (p["kind"], p["tags"]) == ("whiteboard", ["wrong"])
    assert len(meta(store, ref["slug"])) == 4


def test_a_revert_never_coalesces(store):
    ref = human(store, "x")
    first = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["a"])["pages"][0]
    out = ok(store, "revert", revision=first["revision"])  # within the window
    assert out["revision"] != first["revision"]
    after = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["b"])["pages"][0]
    assert after["revision"] not in (first["revision"], out["revision"])
    assert len(meta(store, ref["slug"])) == 3
    again = ok(store, "revert", revision=first["revision"])  # the same state: no-op
    assert again["revision"] is not None  # b goes: a change
    assert ok(store, "revert", revision=first["revision"])["revision"] is None


def test_revert_of_a_missing_revision_or_a_trashed_page(store):
    assert "no such page" in refused(store, "revert", revision=999)
    ref = human(store, "x")
    rev = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["a"])["pages"][0]
    store.delete_page(ref["slug"])
    assert "no such page" in refused(store, "revert", revision=rev["revision"])


def test_web_tag_and_kind_edits_are_revisions_too(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    store = Store(tmp_path / "data")
    ref = human(store, "x")
    headers = {"Tailscale-User-Login": "giles@example.com"}
    url = f"/api/pages/{ref['page_id']}"
    before = client.get(url).json()
    client.patch(url, json={"tags": ["a"], "kind": "todo"}, headers=headers)
    client.patch(url, json={"tags": ["a"]}, headers=headers)  # the same: no change
    [rev] = store.revisions(ref["slug"])["meta"]
    assert (rev["author"], rev["source"]) == ("giles@example.com", "web")
    assert (rev["kind_before"], rev["kind_after"]) == ("note", "todo")
    after = client.get(url).json()
    assert after["updated_at"] == before["updated_at"]  # as before this change


def test_append_records_the_tags_it_adds(store):
    w = write(store, tags=["a"])
    ok(store, "write", title="", body="more", origin="", append_to=w["id"], tags=["b"])
    [rev] = meta(store, w["slug"])
    assert (rev["tags_before"], rev["tags_after"]) == (["a"], ["a", "b"])


def test_revisions_list_text_revisions_and_return_one(store):
    w = write(store, body="first")
    ok(store, "write", title="", body="second", origin="", append_to=w["id"])
    out = ok(store, "revisions", page=w["slug"], text_rev=1)
    assert [r["rev"] for r in out["text"]] == [2, 1]
    assert out["text"][0]["author"] == "claude" and out["text"][1]["bytes"] == 5
    assert out["text_revision"]["body"] == "first"
    assert "no such page" in refused(store, "revisions", page=w["slug"], text_rev=9)


def test_no_mcp_tool_can_delete_or_overwrite_text(store):
    """Every tool, and every argument it takes: none deletes a page or writes the text
    of one the user made (write's body only adds, and appends only to Claude's)."""

    async def main():
        async with Client(mcp_server.server(store)) as client:
            return (await client.list_tools()).tools

    tools = {t.name: set(t.input_schema["properties"]) for t in anyio.run(main)}
    assert not [n for n in tools if any(w in n for w in ("delete", "trash", "purge"))]
    for name, args in tools.items():
        if name != "write":
            assert not args & {"body", "title", "text", "fields", "status"}, name
    ref = human(store, "my own words", tags=["t"])
    ok(store, "edit_meta", pages=[ref["slug"]], kind="todo", set_tags=["u"])
    rev = meta(store, ref["slug"])[0]["id"]
    ok(store, "revert", revision=rev)
    ok(store, "rename_tag", old="t", new="v")
    p = store.page(ref["page_id"])
    assert (p["title"], p["body"], p["rev"]) == ("my own words", "my own words", 1)


def test_migration_8_is_additive_and_can_run_again(tmp_path):
    """An older scrap runs with user_version set back to 7: migrating again keeps the
    table and its rows."""
    store = Store(tmp_path)
    store.migrate()
    ref = human(store, "x")
    store.edit_meta([ref["slug"]], "claude", "mcp", add=["a"])
    with closing(connect(store.db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
        conn.execute("PRAGMA user_version = 7")
    store.migrate()
    with closing(connect(store.db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
    assert len(store.revisions(ref["slug"])["meta"]) == 1


def test_a_new_page_has_no_metadata_revision(store):
    ref = human(store, "x", tags=["a"], kind="todo")
    assert store.revisions(ref["slug"])["meta"] == []
    assert [r["rev"] for r in store.revisions(ref["slug"])["text"]] == [1]
