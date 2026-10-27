"""Kinds and tags edited over MCP (edit_meta, rename_tag), on any page, and the
metadata revisions that make every such edit visible and revertible."""

import re
from contextlib import closing

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client

from scrap import mcp_server
from scrap.app import create_app
from scrap.store import Store, connect
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
    out = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["t"])
    assert out["changed"] == 0 and out["pages"][0]["revision"] is None
    assert meta(store, ref["slug"]) == []


def test_edit_meta_refuses_bad_requests(store):
    ref = human(store)
    for args, error in [
        ({"kind": "memo"}, "kind must be one of"),
        ({"kind": "bogus"}, "kind must be one of"),
        ({}, "nothing to change"),
        ({"add_tags": ["a"], "set_tags": ["b"]}, "replace them all"),
        ({"add_tags": ["a"], "remove_tags": ["A"]}, "both added and removed"),
        ({"add_tags": ["x" * 65]}, "1 to 64 characters"),
    ]:
        assert error in refused(store, "edit_meta", pages=[ref["slug"]], **args)
    assert "not both" in refused(
        store, "edit_meta", pages=[ref["slug"]], query="x", kind="todo"
    )
    assert "give pages or a query" in refused(store, "edit_meta", kind="todo")
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
    assert "merge" in refused(store, "rename_tag", old="proj", new="project")
    dry = ok(store, "rename_tag", old="proj", new="project", merge=True, dry_run=True)
    assert dry["changed"] == 2 and store.page(a["slug"])["tags"] != []
    assert sorted(store.page(a["slug"])["tags"]) == ["keep", "proj", "proj/x"]
    ok(store, "rename_tag", old="proj", new="Project", merge=True)
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
    first = store.edit_meta([ref["slug"]], "claude", "mcp", add=["a"])["pages"][0]
    with closing(connect(store.db)) as conn:
        conn.execute("INSERT INTO tag VALUES (?, 'by-ingest')", (ref["page_id"],))
    second = store.edit_meta([ref["slug"]], "claude", "mcp", add=["b"])["pages"][0]
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
    assert "no such revision 999" in refused(store, "revert", revision=999)
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
    edit = client.patch(url, json={"tags": ["a"], "kind": "todo"}, headers=headers)
    assert edit.status_code == 200
    same = client.patch(url, json={"tags": ["a"]}, headers=headers)  # no change
    assert same.status_code == 200
    stale = {"base_rev": 9, "body": "y", "tags": ["b"]}
    assert client.patch(url, json=stale, headers=headers).status_code == 409
    [rev] = store.revisions(ref["slug"])["meta"]
    assert (rev["author"], rev["source"]) == ("giles@example.com", "web")
    assert (rev["kind_before"], rev["kind_after"]) == ("note", "todo")
    assert (rev["fixed_before"], rev["fixed_after"]) == (False, True)
    assert rev["fields_added"] == {"status": "open"}
    after = client.get(url).json()
    assert after["updated_at"] == before["updated_at"]  # as before this change
    assert after["tags"] == ["a"]  # the stale edit saved nothing, nor a revision


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
    error = refused(store, "revisions", page=w["slug"], text_rev=9)
    assert "no such revision 9" in error


def test_no_mcp_tool_can_delete_or_overwrite_text(store):
    """Every tool, and every argument it takes: none deletes a page for good (only
    trash_pages moves one to the trash: test_mcp_trash), and none but write
    (adds, and appends only to Claude's) and edit_page (a revision: see
    test_content_edit) writes the text of one the user made."""

    async def main():
        async with Client(mcp_server.server(store)) as client:
            return (await client.list_tools()).tools

    tools = {t.name: set(t.input_schema["properties"]) for t in anyio.run(main)}
    # the trash can be listed, filled and a page brought back, never emptied or purged
    risky = {n for n in tools if re.search("delete|trash|purge|remove|empty", n)}
    assert risky == {"trash", "trash_pages", "undelete"}
    for name, args in tools.items():
        if name not in ("write", "edit_page"):
            assert not args & {"body", "title", "text", "status"}, name
            # fields only as edit_meta's metadata revision (#309), which revert undoes
            assert ("fields" in args) == (name == "edit_meta"), name
    ref = human(store, "my own words", tags=["t"])
    ok(store, "edit_meta", pages=[ref["slug"]], kind="todo", set_tags=["u"])
    rev = meta(store, ref["slug"])[0]["id"]
    ok(store, "revert", revision=rev)
    ok(store, "rename_tag", old="t", new="v")
    p = store.page(ref["page_id"])
    assert (p["title"], p["body"], p["rev"]) == ("my own words", "my own words", 1)


def test_a_new_page_has_no_metadata_revision(store):
    ref = human(store, "x", tags=["a"], kind="todo")
    assert store.revisions(ref["slug"])["meta"] == []
    assert [r["rev"] for r in store.revisions(ref["slug"])["text"]] == [1]


def fixed(store, key):
    p = store.page(key)
    return p["kind"], p["kind_fixed"], p["fields"]


def test_revert_unpins_the_kind_and_takes_off_its_defaults(store):
    ref = human(store, "x")  # a note nobody filed: unfixed
    assert fixed(store, ref["slug"]) == ("note", 0, {})
    rev = ok(store, "edit_meta", pages=[ref["slug"]], kind="todo")["pages"][0]
    assert rev["fields_added"] == {"status": "open"} and rev["fixed_after"]
    assert fixed(store, ref["slug"]) == ("todo", 1, {"status": "open"})
    out = ok(store, "revert", revision=rev["revision"])
    assert out["fields_removed"] == {"status": "open"} and not out["fixed_after"]
    assert fixed(store, ref["slug"]) == ("note", 0, {})
    # a box makes it a todo again by itself: it follows its text as before
    store.update_page(ref["slug"], 1, None, "- [ ] a", "me")
    assert store.page(ref["slug"])["kind"] == "todo"


def test_revert_keeps_a_default_field_changed_since(store):
    ref = human(store, "x")
    rev = ok(store, "edit_meta", pages=[ref["slug"]], kind="todo")["pages"][0]
    store.update_page(ref["slug"], None, None, None, "me", fields={"status": "done"})
    ok(store, "revert", revision=rev["revision"])
    assert fixed(store, ref["slug"]) == ("note", 0, {"status": "done"})


def test_edit_meta_with_the_current_kind_fixes_it(store):
    """As the PWA's PATCH with a kind: chosen, so ingest and task boxes keep it."""
    ref = human(store, "x")
    out = ok(store, "edit_meta", pages=[ref["slug"]], kind="note")["pages"][0]
    assert out["changed"] and out["revision"]
    assert (out["fixed_before"], out["fixed_after"]) == (False, True)
    assert fixed(store, ref["slug"]) == ("note", 1, {})
    store.update_page(ref["slug"], 1, None, "- [ ] a", "me")
    assert store.page(ref["slug"])["kind"] == "note"


def test_a_burst_that_changes_nothing_leaves_no_revision(store):
    ref = human(store, "x")
    ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["a"])
    out = ok(store, "edit_meta", pages=[ref["slug"]], remove_tags=["a"])
    assert out["pages"][0]["revision"] is None
    assert meta(store, ref["slug"]) == []


def test_reverting_a_coalesced_revision_undoes_the_whole_burst(store):
    ref = human(store, "x", tags=["mine"])
    ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["a"])
    ok(store, "edit_meta", pages=[ref["slug"]], kind="doc", remove_tags=["mine"])
    [rev] = meta(store, ref["slug"])
    ok(store, "revert", revision=rev["id"])
    assert fixed(store, ref["slug"]) == ("note", 0, {})
    assert store.page(ref["slug"])["tags"] == ["mine"]


def test_rename_tag_guards(store):
    human(store, "a", tags=["a"])
    human(store, "b", tags=["a/x"])
    assert "nest" in refused(store, "rename_tag", old="a", new="a/b")
    assert "more than 1" in refused(store, "rename_tag", old="a", new="z", limit=1)
    assert "is in use" in refused(store, "rename_tag", old="a/x", new="a")
    out = ok(store, "rename_tag", old="a", new="z")
    assert out["changed"] == 2 and out["batch"]


def test_a_bulk_edit_is_one_batch_revert_undoes_at_once(store):
    refs = [human(store, f"Board {n}", tags=["meeting"]) for n in range(3)]
    out = ok(store, "edit_meta", query="tag:meeting", kind="board", add_tags=["wb"])
    batch = out["batch"]
    assert batch and all(p["batch"] == batch for p in out["pages"])
    listed = ok(store, "revisions", batch=batch)["meta"]
    assert len(listed) == 3 and {r["batch_id"] for r in listed} == {batch}
    assert {r["slug"] for r in listed} == {r["slug"] for r in refs}
    assert len(ok(store, "revisions", page=refs[0]["slug"], batch=batch)["meta"]) == 1
    dry = ok(store, "revert", batch=batch, dry_run=True)
    assert dry["batch"] is None and len(dry["pages"]) == 3 and not dry["conflicts"]
    assert {store.page(r["slug"])["kind"] for r in refs} == {"whiteboard"}  # unsaved
    undo = ok(store, "revert", batch=batch)
    assert undo["batch"] and undo["batch"] != batch and undo["reverts_batch"] == batch
    for r in refs:
        assert fixed(store, r["slug"]) == ("note", 0, {})
        assert store.page(r["slug"])["tags"] == ["meeting"]
    # and the batch revert, as a whole
    ok(store, "revert", batch=undo["batch"])
    assert {store.page(r["slug"])["kind"] for r in refs} == {"whiteboard"}


def test_bulk_edits_never_coalesce(store):
    ref = human(store, "x")
    one = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["a"])  # single
    two = ok(store, "edit_meta", query="tag:a", add_tags=["b"])  # a batch of one
    assert two["batch"] and one["batch"] is None
    three = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["c"])
    ids = [x["pages"][0]["revision"] for x in (one, two, three)]
    assert len(set(ids)) == 3  # nothing folds into or out of the batch's revision
    # a batch of one, changed since (c): refused, never clobbered
    assert "changed since" in refused(store, "revert", batch=two["batch"])
    assert store.page(ref["slug"])["tags"] == ["a", "b", "c"]


def test_batch_revert_refuses_a_page_changed_since(store):
    refs = [human(store, f"P {n}", tags=["t"]) for n in range(2)]
    batch = ok(store, "edit_meta", query="tag:t", add_tags=["u"])["batch"]
    ok(store, "edit_meta", pages=[refs[0]["slug"]], add_tags=["later"])
    dry = ok(store, "revert", batch=batch, dry_run=True)
    assert [c["slug"] for c in dry["conflicts"]] == [refs[0]["slug"]]
    error = refused(store, "revert", batch=batch)
    assert refs[0]["slug"] in error and "nothing was reverted" in error
    assert store.page(refs[1]["slug"])["tags"] == ["t", "u"]  # untouched
    assert sorted(store.page(refs[0]["slug"])["tags"]) == ["later", "t", "u"]


def test_batch_revert_skips_a_trashed_page_and_unknown_batches(store):
    refs = [human(store, f"P {n}", tags=["t"]) for n in range(2)]
    batch = ok(store, "edit_meta", query="tag:t", kind="doc")["batch"]
    store.delete_page(refs[0]["slug"])
    out = ok(store, "revert", batch=batch)
    assert [s["id"] for s in out["skipped"]] == [refs[0]["page_id"]]
    assert store.page(refs[1]["slug"])["kind"] == "note"
    assert "no such batch NOPE" in refused(store, "revert", batch="NOPE")
    assert "exactly one of revision, batch" in refused(store, "revert")
    both = refused(store, "revert", revision=1, batch="x")
    assert "exactly one of revision, batch" in both


def test_a_revision_id_is_never_used_again(store):
    """A burst that changes nothing is dropped: its id must not then name another
    page's revision, or a revert of it would change the wrong page."""
    a, b = human(store, "A"), human(store, "B")
    first = ok(store, "edit_meta", pages=[a["slug"]], add_tags=["x"])["pages"][0]
    ok(store, "edit_meta", pages=[a["slug"]], remove_tags=["x"])  # burst dropped
    assert meta(store, a["slug"]) == []
    other = ok(store, "edit_meta", pages=[b["slug"]], add_tags=["y"])["pages"][0]
    assert other["revision"] != first["revision"]
    assert "no such revision" in refused(store, "revert", revision=first["revision"])
    assert store.page(b["slug"])["tags"] == ["y"]


def test_one_page_named_twice_is_not_a_batch(store):
    ref = human(store, "x")
    out = ok(store, "edit_meta", pages=[ref["slug"], ref["page_id"]], add_tags=["a"])
    assert out["matched"] == 1 and out["batch"] is None
    two = ok(store, "edit_meta", pages=[ref["slug"]], add_tags=["b"])
    assert two["pages"][0]["revision"] == out["pages"][0]["revision"]  # folded


def test_revisions_of_a_whole_batch_and_more(store):
    refs = [human(store, f"P {n}", tags=["t"]) for n in range(60)]
    batch = ok(store, "edit_meta", query="tag:t", add_tags=["u"], limit=60)["batch"]
    whole = ok(store, "revisions", batch=batch, limit=200)
    assert len(whole["meta"]) == 60 and not whole["more"]
    part = ok(store, "revisions", batch=batch, limit=50)
    assert len(part["meta"]) == 50 and part["more"]
    assert not ok(store, "revisions", page=refs[0]["slug"])["more"]


def test_rename_into_a_tag_only_in_the_trash_needs_merge(store):
    human(store, "a", tags=["a"])
    gone = human(store, "b", tags=["b"])
    store.delete_page(gone["slug"])
    assert "only in the trash" in refused(store, "rename_tag", old="a", new="b")
    assert ok(store, "rename_tag", old="a", new="b", merge=True)["changed"] == 1


def test_edit_meta_kind_change_on_a_full_page_loses_nothing(store):
    ref = human(store, "Crowded")
    full = {f"k{n}": "x" for n in range(32)}
    store.update_page(ref["slug"], None, None, None, "giles", fields=full)
    out = ok(store, "edit_meta", pages=[ref["slug"]], kind="todo")
    assert out["changed"] == 1
    assert store.page(ref["page_id"])["fields"] == full


# ---- edit_meta's fields (#309): a Later's media_type, and its subtype that follows


def later(store, title, **fields):
    ref = human(store, title)
    ok(store, "edit_meta", pages=[ref["slug"]], kind="read")  # a Later: subtype read
    if fields:
        store.update_page(ref["slug"], None, None, None, "me", fields=fields)
    return ref


def test_edit_meta_sets_media_type_and_its_subtype(store):
    ref = later(store, "Film night")
    out = ok(store, "edit_meta", pages=[ref["slug"]], fields={"media_type": "film"})
    row = out["pages"][0]
    assert row["fields_added"] == {"media_type": "film", "subtype": "watch"}
    assert row["fields_was"] == {"subtype": "read"}  # (media_type was not there)
    assert row["changed"] and row["revision"]
    fields = store.page(ref["slug"])["fields"]
    assert (fields["media_type"], fields["subtype"], fields["status"]) == (
        "film", "watch", "open",
    )  # fmt: skip
    assert [p["slug"] for p in store.search("later:watch", 5)] == [ref["slug"]]
    assert [p["slug"] for p in store.search("media:film", 5)] == [ref["slug"]]


def test_edit_meta_fields_dry_run_saves_nothing(store):
    ref = later(store, "Podcast")
    dry = ok(
        store, "edit_meta", pages=[ref["slug"]], fields={"media_type": "podcast"},
        dry_run=True,
    )  # fmt: skip
    assert dry["dry_run"] and dry["pages"][0]["revision"] is None
    assert dry["pages"][0]["fields_added"]["subtype"] == "listen"
    assert "media_type" not in store.page(ref["slug"])["fields"]


def test_a_fields_change_in_a_batch_is_reverted_with_its_values(store):
    a, b = later(store, "A", media_type="book"), later(store, "B")
    out = ok(
        store, "edit_meta", pages=[a["slug"], b["slug"]],
        fields={"media_type": "game"},
    )  # fmt: skip
    batch = out["batch"]
    assert batch and store.page(a["slug"])["fields"]["subtype"] == "play"
    undo = ok(store, "revert", batch=batch)
    assert undo["reverts_batch"] == batch
    fa, fb = store.page(a["slug"])["fields"], store.page(b["slug"])["fields"]
    assert (fa["media_type"], fa["subtype"]) == ("book", "read")  # changed back
    assert "media_type" not in fb and fb["subtype"] == "read"  # taken off / back
    # and the revert is undone in turn
    ok(store, "revert", batch=undo["batch"])
    assert store.page(a["slug"])["fields"]["media_type"] == "game"
    assert store.page(b["slug"])["fields"]["subtype"] == "play"


def test_a_field_can_be_taken_off_and_reverted(store):
    ref = later(store, "A", media_type="tv", subtype="watch")
    for made in meta(store, ref["slug"]):
        age(store, made["id"])  # the kind change is its own revision
    out = ok(store, "edit_meta", pages=[ref["slug"]], fields={"media_type": None})
    assert out["pages"][0]["fields_was"] == {"media_type": "tv", "subtype": "watch"}
    assert "media_type" not in store.page(ref["slug"])["fields"]
    ok(store, "revert", revision=out["pages"][0]["revision"])
    fields = store.page(ref["slug"])["fields"]
    assert (fields["media_type"], fields["subtype"]) == ("tv", "watch")


def test_a_revert_keeps_a_field_changed_since(store):
    ref = later(store, "A")
    rev = ok(store, "edit_meta", pages=[ref["slug"]], fields={"media_type": "film"})
    store.update_page(ref["slug"], None, None, None, "me", fields={"subtype": "listen"})
    ok(store, "revert", revision=rev["pages"][0]["revision"])
    fields = store.page(ref["slug"])["fields"]
    assert "media_type" not in fields and fields["subtype"] == "listen"


def test_edit_meta_refuses_bad_fields(store):
    ref = later(store, "A")
    key = ref["slug"]
    assert "subtype follows" in refused(
        store, "edit_meta", pages=[key], fields={"subtype": "play"}
    )
    assert "media_type must be" in refused(
        store, "edit_meta", pages=[key], fields={"media_type": "pigeon"}
    )
    assert "cannot be set here" in refused(
        store, "edit_meta", pages=[key], fields={"x": 2**60}
    )
    assert "nothing to change" in refused(store, "edit_meta", pages=[key])
    assert "subtype" in store.page(key)["fields"]  # nothing saved


def test_folded_field_edits_revert_to_what_was_never_there(store):
    ref = later(store, "Fold")
    for made in meta(store, ref["slug"]):
        age(store, made["id"])  # the kind change is its own revision
    ok(store, "edit_meta", pages=[ref["slug"]], fields={"media_type": "book"})
    two = ok(store, "edit_meta", pages=[ref["slug"]], fields={"media_type": "film"})
    revs = meta(store, ref["slug"])
    rev = next(r for r in revs if r["id"] == two["pages"][0]["revision"])
    assert rev["fields_added"]["media_type"] == "film"
    assert "media_type" not in rev["fields_was"]  # not made up from the first edit
    assert rev["fields_was"] == {"subtype": "read"}
    ok(store, "revert", revision=two["pages"][0]["revision"])
    fields = store.page(ref["slug"])["fields"]
    assert "media_type" not in fields and fields["subtype"] == "read"


def test_edit_meta_refuses_reserved_and_unpaired_fields(store):
    ref = later(store, "A")
    key = ref["slug"]
    for name in ("personal", "source", "summary", "title", "body", "_x", ""):
        assert "cannot be set here" in refused(
            store, "edit_meta", pages=[key], fields={name: "x"}
        )
    note = human(store, "Plain")  # not a Later: media_type would pair with read
    assert "make it one first" in refused(
        store, "edit_meta", pages=[note["slug"]], fields={"media_type": "film"}
    )
    assert "media_type" not in store.page(note["slug"])["fields"]
    both = ok(  # but with the kind change in the same call it is fine
        store, "edit_meta", pages=[note["slug"]], kind="read",
        fields={"media_type": "film"},
    )  # fmt: skip
    assert both["pages"][0]["fields_added"]["subtype"] == "watch"


# ---- edit_meta's status: a todo ticked done and reopened over MCP


def todo(store, title="Buy milk"):
    ref = human(store, title)
    made = ok(store, "edit_meta", pages=[ref["slug"]], kind="todo")
    age(store, made["pages"][0]["revision"])  # its own revision: later ones don't fold
    return ref["slug"]


def test_edit_meta_marks_a_todo_done_and_reopens_it(store):
    key = todo(store)
    dry = ok(store, "edit_meta", pages=[key], fields={"status": "done"}, dry_run=True)
    assert dry["pages"][0]["revision"] is None and dry["pages"][0]["changed"]
    assert store.page(key)["fields"]["status"] == "open"  # nothing saved
    done = ok(store, "edit_meta", pages=[key], fields={"status": "done"})
    row = done["pages"][0]
    assert row["fields_added"] == {"status": "done"} and row["fields_was"] == {
        "status": "open"
    }
    assert store.page(key)["fields"]["status"] == "done"
    assert [p["slug"] for p in store.search("is:done", 5)] == [key]
    rev = meta(store, key)[0]
    assert rev["source"] == "mcp" and rev["id"] == row["revision"]
    ok(store, "edit_meta", pages=[key], fields={"status": "open"})  # reopen
    assert store.page(key)["fields"]["status"] == "open"


def test_a_status_change_is_reverted(store):
    key = todo(store)
    rev = ok(store, "edit_meta", pages=[key], fields={"status": "done"})
    ok(store, "revert", revision=rev["pages"][0]["revision"])
    assert store.page(key)["fields"]["status"] == "open"


def test_edit_meta_refuses_a_bad_status(store):
    key = todo(store)
    assert "status must be" in refused(
        store, "edit_meta", pages=[key], fields={"status": "finished"}
    )
    assert "status must be" in refused(
        store, "edit_meta", pages=[key], fields={"status": None}
    )
    note = human(store, "Just a note")["slug"]
    assert "make it one first" in refused(
        store, "edit_meta", pages=[note], fields={"status": "done"}
    )
    assert store.page(key)["fields"]["status"] == "open"


def test_status_with_a_kind_change_is_refused_and_a_later_takes_one(store):
    note = human(store, "Just a note")["slug"]
    assert "earlier call" in refused(
        store, "edit_meta", pages=[note], kind="todo", fields={"status": "done"}
    )
    assert store.page(note)["kind"] == "note"
    film = later(store, "Film")["slug"]
    ok(store, "edit_meta", pages=[film], fields={"status": "cancelled"})
    assert store.page(film)["fields"]["status"] == "cancelled"
