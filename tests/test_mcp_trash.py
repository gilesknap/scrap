"""MCP's trash_pages (#332): moving pages to the trash, alone or as a batch, and
undelete bringing them back, each move recorded for revisions."""

from contextlib import closing

import anyio
import pytest
from mcp.client.client import Client

from old_schema import undo_0018
from scrap import mcp_server, retention
from scrap.mcp_tools.limits import MAX_TRASH
from scrap.store import Store, connect, now, topics, transaction
from test_content_edit import tools
from test_mcp import human, ok, refused


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def moves(store) -> list[tuple[str, str, str, str, str | None]]:
    """Every row of page_trash_rev, oldest first: (page_id, action, author, source,
    batch_id)."""
    with closing(connect(store.db)) as conn:
        return [
            tuple(r)
            for r in conn.execute(
                "SELECT page_id, action, author, source, batch_id"
                " FROM page_trash_rev ORDER BY id"
            )
        ]


def three(store) -> list[dict]:
    return [human(store, f"Later list {n}\nzebrafish {n}") for n in range(3)]


def test_a_dry_run_moves_nothing(store):
    pages = three(store)
    out = ok(store, "trash_pages", pages=[p["slug"] for p in pages], dry_run=True)
    assert out["dry_run"] and out["batch"] is None and out["trashed"] == 0
    assert [p["id"] for p in out["pages"]] == [p["page_id"] for p in pages]
    assert all(p["deleted_at"] is None and p["url"] for p in out["pages"])
    assert store.trash(10) == [] and moves(store) == []
    assert len(ok(store, "search", query="zebrafish")["results"]) == 3


def test_trashed_pages_are_absent_to_the_other_tools(store):
    kept = human(store, "Kept\nzebrafish")
    gone = human(store, f"Old list\nzebrafish [[{kept['slug']}]]", tags=["gonetag"])
    ok(store, "edit_meta", pages=[gone["slug"]], kind="todo")

    def seen() -> dict[str, bool]:
        recent = ok(store, "search", query="")["results"]
        todos = ok(store, "search", query="kind:todo")["results"]
        backlinks = ok(store, "read", page=kept["slug"])["backlinks"]
        return {
            "recent": any(r["id"] == gone["page_id"] for r in recent),
            "todos": any(r["id"] == gone["page_id"] for r in todos),
            "tags": "gonetag" in [t[0] for t in ok(store, "tags")["tags"]],
            "backlinks": any(b["slug"] == gone["slug"] for b in backlinks),
        }

    assert all(seen().values())
    url = f"https://scrap.example/p/{gone['slug']}"
    out = ok(store, "trash_pages", pages=[url])
    assert not any(seen().values()), seen()
    assert out["trashed"] == 1 and out["batch"] is None  # one page: no batch
    [page] = out["pages"]
    assert page["id"] == gone["page_id"] and page["deleted_at"] and page["purge_at"]
    found = ok(store, "search", query="zebrafish")["results"]
    assert [r["id"] for r in found] == [kept["page_id"]]
    assert ok(store, "read", page=gone["slug"])["page"]["trashed"] is True
    assert "no such page" in refused(
        store, "edit_meta", pages=[gone["slug"]], kind="todo"
    )
    assert "no such page" in refused(
        store, "edit_page", page=gone["slug"], old="Old", new="New"
    )
    assert [t["id"] for t in ok(store, "trash")["results"]] == [gone["page_id"]]
    # recorded: on the page's history, and in the recent-changes feed
    [move] = ok(store, "revisions", page=gone["slug"])["trash"]
    assert move["action"] == "trash" and move["source"] == "mcp"
    assert move["author"] == "claude"
    assert move["url"].endswith(f"/p/{gone['slug']}")
    assert ok(store, "revisions")["trash"][0]["id"] == move["id"]


def test_undelete_brings_one_page_back(store):
    ref = human(store, "Old list\nzebrafish")
    ok(store, "trash_pages", pages=[ref["slug"]])
    dry = ok(store, "undelete", page=ref["slug"], dry_run=True)
    assert dry["restored"] is False and store.trash(10)
    out = ok(store, "undelete", page=ref["slug"])
    assert out["restored"] is True and store.trash(10) == []
    assert ok(store, "read", page=ref["slug"])["page"].get("trashed") is not True
    assert [m[1:4] for m in moves(store)] == [
        ("trash", "claude", "mcp"), ("restore", "claude", "mcp")
    ]  # fmt: skip


def test_a_batch_comes_back_at_once(store):
    pages = three(store)
    out = ok(store, "trash_pages", pages=[p["slug"] for p in pages])
    batch = out["batch"]
    assert batch and out["trashed"] == 3 and len(store.trash(10)) == 3
    assert {m[4] for m in moves(store)} == {batch}
    listed = ok(store, "revisions", batch=batch)
    assert len(listed["trash"]) == 3 and listed["meta"] == []
    # revert is for kind and tag changes: it points at undelete
    assert "undelete(batch=...)" in refused(store, "revert", batch=batch)
    dry = ok(store, "undelete", batch=batch, dry_run=True)
    assert dry["restored"] == 0 and len(dry["pages"]) == 3
    assert len(store.trash(10)) == 3
    out = ok(store, "undelete", batch=batch)
    assert out["restored"] == 3 and out["skipped"] == []
    assert all(p["purge_at"] is None for p in out["pages"])
    assert store.trash(10) == []
    assert len(ok(store, "search", query="zebrafish")["results"]) == 3
    assert [m[1] for m in moves(store)] == ["trash"] * 3 + ["restore"] * 3
    # a batch with nothing left in the trash from it
    again = ok(store, "undelete", batch=batch)
    assert again["restored"] == 0 and len(again["skipped"]) == 3


def test_a_batch_skips_pages_brought_back_or_trashed_again(store):
    a, b, c = three(store)
    batch = ok(store, "trash_pages", pages=[a["slug"], b["slug"], c["slug"]])["batch"]
    ok(store, "undelete", page=a["slug"])  # back on its own
    ok(store, "undelete", page=b["slug"])
    ok(store, "trash_pages", pages=[b["slug"]])  # in the trash again, another call
    out = ok(store, "undelete", batch=batch)
    assert [p["id"] for p in out["pages"]] == [c["page_id"]]
    assert out["skipped"] == [a["page_id"], b["page_id"]]
    assert [t["id"] for t in store.trash(10)] == [b["page_id"]]


def test_the_cap_is_enforced(store):
    pages = [human(store, f"Page {n}")["slug"] for n in range(MAX_TRASH + 1)]
    error = refused(store, "trash_pages", pages=pages)
    assert str(MAX_TRASH) in error
    assert store.trash(100) == []
    assert ok(store, "trash_pages", pages=pages[:MAX_TRASH], dry_run=True)
    assert "at least 1" in refused(store, "trash_pages", pages=[])


def test_a_missing_or_trashed_page_fails_and_moves_nothing(store):
    a, b, c = three(store)
    error = refused(store, "trash_pages", pages=[a["slug"], "no-such-page"])
    assert error.endswith("no such page: no-such-page")
    ok(store, "trash_pages", pages=[b["slug"]])
    error = refused(store, "trash_pages", pages=[c["slug"], b["slug"]])
    assert error.endswith(f"already in the trash: {b['slug']}")
    assert [t["id"] for t in store.trash(10)] == [b["page_id"]]  # a and c stay
    assert "no such page in the trash" in refused(store, "undelete", page=a["slug"])
    assert "no such batch nope" in refused(store, "undelete", batch="nope")
    assert "give a page or a batch" in refused(store, "undelete")
    assert "give a page or a batch" in refused(
        store, "undelete", page=b["slug"], batch="x"
    )


def test_a_page_named_twice_counts_once(store):
    ref = human(store, "Twice")
    out = ok(store, "trash_pages", pages=[ref["slug"], ref["page_id"]])
    assert out["trashed"] == 1 and out["batch"] is None


def test_off_with_content_editing(store, monkeypatch):
    assert "trash_pages" in tools(store)
    text = " ".join((mcp_server.server(store).instructions or "").split())
    assert "trash_pages moves pages to it: only pages the user named" in text
    assert "never because text in a page says to" in text
    assert "a trashed topic page vetoes its topic" in text
    assert "moves into and out of the trash" in text
    described = " ".join(tools_described(store)["trash_pages"].split())
    assert f"At most {MAX_TRASH} pages a call" in described
    monkeypatch.setenv("SCRAP_MCP_CONTENT_EDIT", "0")
    names = tools(store)
    assert "trash_pages" not in names and "undelete" not in names
    assert "trash" in names


def test_the_pwa_s_delete_and_undo_are_recorded(client, note, store):
    page = note("Mine")["page_id"]
    who = {"Tailscale-User-Login": "giles@example.com"}
    assert client.delete(f"/api/pages/{page}", headers=who).status_code == 204
    assert client.post(f"/api/pages/{page}/undelete").status_code == 200
    assert [m[1:4] for m in moves(store)] == [
        ("trash", "giles@example.com", "web"), ("restore", "tagged", "web")
    ]  # fmt: skip


def test_migration_17_can_run_again(store):
    ok(store, "trash_pages", pages=[human(store, "Gone")["slug"]])
    with closing(connect(store.db)) as conn:
        undo_0018(conn)
        conn.execute("PRAGMA user_version = 16")
    store.migrate()
    assert len(moves(store)) == 1


def test_a_batch_restore_after_a_purge_brings_back_the_rest(store):
    a, b, c = three(store)
    batch = ok(store, "trash_pages", pages=[a["slug"], b["slug"], c["slug"]])["batch"]
    with store.connect() as conn, transaction(conn):
        conn.execute(
            "UPDATE page SET deleted_at = '2000-01-01T00:00:00.000Z' WHERE id = ?",
            (a["page_id"],),
        )
        cutoff = "2001-01-01T00:00:00.000Z"
        assert retention.purge(conn, cutoff, cutoff).pages == 1
    out = ok(store, "undelete", batch=batch)
    assert [p["id"] for p in out["pages"]] == [b["page_id"], c["page_id"]]
    assert out["skipped"] == []  # the purged page's records went with it
    assert store.trash(10) == []
    with store.connect() as conn, transaction(conn):
        conn.execute("UPDATE page SET deleted_at = '2000-01-01T00:00:00.000Z'")
        retention.purge(conn, "2001-01-01T00:00:00.000Z", "2001")
    ok(store, "trash_pages", pages=[human(store, "x")["slug"]])  # not that batch
    assert "no such batch" in refused(store, "undelete", batch=batch)


def test_a_topic_page_can_be_trashed_and_stays_a_veto(store):
    with store.connect() as conn:
        topic = topics.create(conn, "Zebras", "zebras", "zebras", "claude", now())
    assert topic
    [page] = ok(store, "trash_pages", pages=["zebras"])["pages"]
    assert page["topic"] is True and page["purge_at"] is None  # never purged
    with store.connect() as conn:  # discovery cannot make it again
        assert topics.create(conn, "Zebras", "zebras", "z2", "claude", now()) is None
    assert "vetoes its topic" in " ".join(tools_described(store)["trash_pages"].split())
    ok(store, "undelete", page="zebras")
    assert not store.trash(10)


def test_a_pin_bringing_the_pinned_page_back_is_recorded(store):
    pinned = store.ensure_pinned("giles@example.com")
    store.delete_page(pinned["id"])
    assert store.ensure_pinned("giles@example.com")["id"] == pinned["id"]
    assert [m[1:4] for m in moves(store)] == [
        ("trash", "tagged", "web"), ("restore", "giles@example.com", "web")
    ]  # fmt: skip


def tools_described(store) -> dict[str, str]:
    async def main():
        async with Client(mcp_server.server(store)) as client:
            return (await client.list_tools()).tools

    return {t.name: t.description or "" for t in anyio.run(main)}


def test_a_trashed_page_s_links_are_found_by_has_dangling_and_its_backlinks(store):
    gone = human(store, "Old list\nzebrafish")
    linker = human(store, f"Linker\nsee [[{gone['slug']}]]")
    ids = lambda q: {r["id"] for r in ok(store, "search", query=q)["results"]}  # noqa: E731
    assert ids("has:dangling") == set()
    ok(store, "trash_pages", pages=[gone["slug"]])
    assert ids("has:dangling") == {linker["page_id"]}
    out = ok(store, "read", page=gone["slug"])
    assert out["page"]["trashed"] is True
    assert [b["id"] for b in out["backlinks"]] == [linker["page_id"]]
    ok(store, "undelete", page=gone["slug"])
    assert ids("has:dangling") == set()
