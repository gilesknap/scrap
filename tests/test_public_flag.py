"""The public flag (page.public, migration 0020; ADR 43): set through PATCH and
edit_meta as a metadata revision that revert undoes, folded only with another flag
change, one page at a time to public, any number to private, and is:public."""

from contextlib import closing

import pytest

from scrap.store import OneAtATimeError, Store, new_ulid
from scrap.store.db import BASELINE, connect, create_baseline, latest, migrate


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def page(store, text="Notes\nx") -> str:
    c = store.prepare({"id": new_ulid(), "text": text}, [])
    return store.capture(c, [], "me")[0]["page_id"]


def flag(store, page_id) -> int:
    with store.connect() as conn:
        return conn.execute(
            "SELECT public FROM page WHERE id = ?", (page_id,)
        ).fetchone()[0]


def test_0020_adds_the_flag_to_pages_and_revisions(tmp_path):
    path = tmp_path / "old.db"
    with closing(connect(path)) as conn:
        create_baseline(conn)
        conn.execute(
            "INSERT INTO page (id, slug, title, created_at, updated_at)"
            " VALUES ('P', 'p', 'P', 't', 't')"
        )
        conn.execute(
            "INSERT INTO page_meta_rev (page_id, author, source, kind_before,"
            " kind_after, fixed_before, fixed_after, tags_before, tags_after,"
            " created_at, updated_at) VALUES ('P', 'me', 'web', 'note', 'todo', 0, 1,"
            " '[]', '[]', 't', 't')"
        )
        conn.commit()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == BASELINE
    migrate(path)
    with closing(connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == latest()
        assert conn.execute("SELECT public FROM page").fetchone()[0] == 0
        row = conn.execute("SELECT public_before, public_after FROM page_meta_rev")
        assert tuple(row.fetchone()) == (0, 0)
        with pytest.raises(Exception, match="CHECK"):
            conn.execute("UPDATE page SET public = 2")


def test_patch_sets_the_flag_as_a_revision_revert_undoes(store):
    pid = page(store)
    out = store.update_page(pid, None, None, None, "me", public=True)
    assert out["public"] is True and flag(store, pid) == 1
    (rev,) = store.revisions(pid)["meta"]
    assert (rev["public_before"], rev["public_after"]) == (False, True)
    store.revert_meta(rev["id"], "me", "web")
    assert flag(store, pid) == 0


def test_a_flag_change_folds_only_into_a_flag_change(store):
    pid = page(store)
    store.update_page(pid, None, None, None, "me", tags=["a"])
    store.update_page(pid, None, None, None, "me", public=True)
    meta = store.revisions(pid)["meta"]
    assert len(meta) == 2  # the tag change and the flag change stay apart
    store.update_page(pid, None, None, None, "me", public=False)
    meta = store.revisions(pid)["meta"]
    assert len(meta) == 1 and meta[0]["tags_after"] == ["a"]  # on, then off: gone
    store.update_page(pid, None, None, None, "me", public=True)
    store.update_page(pid, None, None, None, "me", tags=["a", "b"])
    assert len(store.revisions(pid)["meta"]) == 3


def test_reverting_another_change_keeps_the_flag(store):
    pid = page(store)
    store.edit_meta([pid], "me", "web", add=["a"])
    tag_rev = store.revisions(pid)["meta"][0]["id"]
    store.edit_meta([pid], "claude", "mcp", public=True)
    store.revert_meta(tag_rev, "me", "web")
    assert flag(store, pid) == 1  # the tag is gone, the page still public
    assert store.page(pid)["tags"] == []


def test_a_batch_revert_keeps_a_flag_changed_since(store):
    a, b = page(store, "A\nx"), page(store, "B\ny")
    batch = store.edit_meta([a, b], "me", "web", add=["t"])["batch"]
    store.edit_meta([a], "me", "web", public=True)
    out = store.revert_batch(batch, "me", "web")
    assert not out["conflicts"] and flag(store, a) == 1
    off = store.edit_meta([a, b], "me", "web", public=False)["batch"]  # bulk private
    assert flag(store, a) == 0
    store.revert_batch(off, "me", "web")  # brings a's flag back
    assert flag(store, a) == 1 and flag(store, b) == 0


def test_public_is_one_page_at_a_time(store):
    a, b = page(store, "A\nx"), page(store, "B\ny")
    for dry in (False, True):
        with pytest.raises(OneAtATimeError):
            store.edit_meta([a, b], "me", "web", public=True, dry_run=dry)
    with pytest.raises(OneAtATimeError):
        store.edit_meta([a, b], "me", "web", public=True, batch=True)  # a query's
    assert flag(store, a) == 0
    store.edit_meta([a, a], "me", "web", public=True)  # one page, named twice
    assert flag(store, a) == 1
    # a query that finds exactly one page makes it public: the matches count
    out = store.edit_meta([b], "me", "web", public=True, batch=True)
    assert flag(store, b) == 1 and out["batch"]


def test_the_api_refuses_with_one_at_a_time(client, note):
    ref = note()
    r = client.patch(f"/api/pages/{ref['slug']}", json={"public": "yes"})
    assert r.status_code == 422  # a bool only
    r = client.patch(f"/api/pages/{ref['slug']}", json={"public": True})
    assert r.json()["public"] is True and r.json()["published_at"] is None
    assert r.json()["public_url"] is None  # no SCRAP_PUBLISH_SITE
    app = client.app
    store = app.state.publisher.store  # type: ignore[attr-defined]
    other = note("Other\ny")
    with pytest.raises(OneAtATimeError) as e:
        store.edit_meta([ref["page_id"], other["page_id"]], "me", "web", public=True)
    assert e.value.code == "one_at_a_time"


def test_is_public(store):
    a, _ = page(store, "Alpha\nshared words"), page(store, "Beta\nshared words")
    store.edit_meta([a], "me", "web", public=True)
    assert [h["id"] for h in store.search("shared is:public", 20)] == [a]
    assert a not in [h["id"] for h in store.search("shared -is:public", 20)]


def test_trash_and_undelete_keep_the_flag(store):
    pid = page(store)
    store.edit_meta([pid], "me", "web", public=True)
    store.delete_page(pid)
    store.delete_page(pid, undo=True)
    assert flag(store, pid) == 1
