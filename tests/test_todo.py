"""Todo richness (#104): a todo's due date and priority, in its page_todo row."""

import pytest

from pagehelp import import_page
from scrap.store import Store, new_ulid


def test_patch_sets_and_clears_due_and_priority(client, note):
    ref = note("Fix the fence", kind="todo")
    url = f"/api/pages/{ref['page_id']}"
    before = client.get(url).json()
    assert (before["due"], before["priority"]) == (None, None)
    set_ = client.patch(url, json={"due": "2026-11-01", "priority": "high"})
    assert set_.status_code == 200, set_.text
    page = set_.json()
    assert (page["due"], page["priority"]) == ("2026-11-01", "high")
    # as status: no new revision, and it stays put in the newest-first list
    assert (page["rev"], page["updated_at"]) == (before["rev"], before["updated_at"])
    assert page["fields"] == {"status": "open"}  # not a field
    only_due = client.patch(url, json={"due": None}).json()  # priority not sent: kept
    assert (only_due["due"], only_due["priority"]) == (None, "high")
    listed = client.get("/api/pages", params={"kind": "todo"}).json()[0]
    assert (listed["due"], listed["priority"]) == (None, "high")
    assert client.patch(url, json={"priority": None}).json()["priority"] is None


@pytest.mark.parametrize(
    "edit",
    [
        {"due": "2026-02-30"},
        {"due": "2026-1-1"},
        {"due": "tomorrow"},
        {"due": "2026-11-01T10:00"},
        {"due": 20261101},
        {"priority": "urgent"},
        {"priority": "High"},
        {"priority": 1},
    ],
)
def test_patch_rejects_a_bad_due_or_priority(client, note, edit):
    url = f"/api/pages/{note('x', kind='todo')['page_id']}"
    assert client.patch(url, json=edit).status_code == 422
    page = client.get(url).json()
    assert (page["due"], page["priority"]) == (None, None)


def test_due_and_priority_are_for_todos(client, note):
    url = f"/api/pages/{note('a note')['page_id']}"
    refused = client.patch(url, json={"due": "2026-11-01"})
    assert refused.status_code == 422
    assert "todo" in refused.json()["detail"]
    assert client.patch(url, json={"priority": "low"}).status_code == 422
    assert client.patch(url, json={"due": None}).status_code == 200  # nothing to clear
    # with the kind in the same edit: made a todo, then given its due date
    todo = client.patch(url, json={"kind": "todo", "due": "2026-11-01"}).json()
    assert (todo["kind"], todo["due"]) == ("todo", "2026-11-01")
    both = client.patch(url, json={"kind": "note", "priority": "low"})
    assert both.status_code == 422  # all or nothing: still a todo
    assert client.get(url).json()["kind"] == "todo"


def test_a_kind_change_keeps_them_but_only_a_todo_shows_them(client, note):
    url = f"/api/pages/{note('x', kind='todo')['page_id']}"
    client.patch(url, json={"due": "2026-11-01", "priority": "medium"})
    as_note = client.patch(url, json={"kind": "note"}).json()
    assert (as_note["due"], as_note["priority"]) == (None, None)
    assert client.get("/api/pages").json()[0]["due"] is None
    back = client.patch(url, json={"kind": "todo"}).json()  # a stray tap loses nothing
    assert (back["due"], back["priority"]) == ("2026-11-01", "medium")


def test_capture_takes_due_and_priority_for_a_todo(client, note):
    ref = note("Call the bank", kind="todo", due="2026-11-02", priority="low")
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert (page["due"], page["priority"]) == ("2026-11-02", "low")
    hinted = note("Old client", hint="todo", priority="high")
    assert client.get(f"/api/pages/{hinted['page_id']}").json()["priority"] == "high"
    for bad in ({"due": "2026-11-02"}, {"kind": "todo", "due": "soon"},
                {"kind": "todo", "priority": "urgent"}):  # fmt: skip
        data = {"id": new_ulid(), "text": "x", **bad}
        assert client.post("/api/captures", json=data).status_code == 422, bad
    multipart = {"id": new_ulid(), "text": "form", "kind": "todo", "due": "2026-11-03"}
    files = [("file", ("a.txt", b"x", "text/plain"))]
    ref = client.post("/api/captures", data=multipart, files=files).json()
    assert client.get(f"/api/pages/{ref['page_id']}").json()["due"] == "2026-11-03"


def test_import_moves_due_and_priority_into_the_todo_row(tmp_path):
    store = Store(tmp_path)
    store.migrate()

    def imported(kind, **fields):
        p = {
            "slug": f"p-{len(store.slugs())}", "title": "T", "body": "", "kind": kind,
            "fields": fields, "tags": [], "created_at": "2026-01-01T00:00:00.000Z",
            "updated_at": "2026-01-01T00:00:00.000Z",
        }  # fmt: skip
        return store.page(
            import_page(store, p, [(new_ulid(), "note", "", [])], "me")[0]
        )

    todo = imported("todo", status="open", due="2026-11-01", priority="urgent")
    assert (todo["due"], todo["priority"], todo["fields"]) == (
        "2026-11-01", "high", {"status": "open"},
    )  # fmt: skip
    odd = imported("todo", due="next week", priority="p1")  # kept as they were
    assert (odd["due"], odd["priority"]) == (None, None)
    assert odd["fields"] == {"due": "next week", "priority": "p1"}
    other = imported("note", due="2026-11-01", priority="high")  # not a todo's
    assert other["fields"] == {"due": "2026-11-01", "priority": "high"}


def test_markdown_carries_due_and_priority_as_front_matter(client, note, tmp_path):
    from scrap.__main__ import main

    ref = note("Fix the fence", kind="todo", due="2026-11-01", priority="high")
    text = client.get(f"/api/pages/{ref['page_id']}/download").text
    assert '\nkind: "todo"\n' in text
    assert '\ndue: "2026-11-01"\npriority: "high"\nstatus: "open"\n' in text
    bare = note("Someday", kind="todo")
    text = client.get(f"/api/pages/{bare['page_id']}/download").text
    assert "\ndue:" not in text and "\npriority:" not in text
    url = f"/api/pages/{ref['page_id']}"
    client.patch(url, json={"kind": "note"})  # kept, but a note's are not exported
    assert "\ndue:" not in client.get(f"{url}/download").text
    client.patch(url, json={"kind": "todo"})
    main(["export", "--data-dir", str(tmp_path / "data"), str(tmp_path / "md")])
    exported = (tmp_path / "md" / f"{ref['slug']}.md").read_text()
    assert '\ndue: "2026-11-01"\npriority: "high"\n' in exported
