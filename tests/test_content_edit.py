"""Page text edited over MCP (edit_page, revert with to_rev): narrow edits of any
page, each a text revision that can be listed and restored, and the switch that
turns them off."""

import difflib
import random
import re
import subprocess
import time
from contextlib import closing

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client

from scrap import mcp_server
from scrap.app import create_app
from scrap.mcp_tools import editing
from scrap.store import Store, connect
from test_mcp import human, ok, refused, write

TEXT = "Shopping list\nmilk and eggs\nbread"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def revs(store, key) -> list[int]:
    return [r["rev"] for r in ok(store, "revisions", page=key)["text"]]


def age(store, page_id: str, stamp="2020-01-01T00:00:00.000Z"):
    """Make a page's text revisions look as if made long ago (outside the window)."""
    with closing(connect(store.db)) as conn:
        conn.execute(
            "UPDATE page_rev SET created_at = ? WHERE page_id = ?", (stamp, page_id)
        )


def tools(store) -> dict[str, set[str]]:
    async def main():
        async with Client(mcp_server.server(store)) as client:
            return (await client.list_tools()).tools

    return {t.name: set(t.input_schema["properties"]) for t in anyio.run(main)}


def test_edit_page_replaces_one_passage_of_a_users_page(store):
    ref = human(store, TEXT)
    out = ok(store, "edit_page", page=ref["slug"], old="milk", new="oat milk", rev=1)
    assert out["changed"] and not out["dry_run"] and out["replacements"] == 1
    assert (out["rev_before"], out["rev"], out["folded"]) == (1, 2, None)
    assert "-milk and eggs\n+oat milk and eggs\n" in out["diff"]
    assert out["url"].endswith(f"/p/{ref['slug']}")
    p = store.page(ref["slug"])
    assert p["body"] == "Shopping list\noat milk and eggs\nbread" and p["rev"] == 2
    assert p["title"] == "Shopping list"  # as it was
    text = ok(store, "revisions", page=ref["slug"], text_rev=1)
    assert [(r["rev"], r["author"]) for r in text["text"]] == [
        (2, "claude"), (1, "giles@example.com"),
    ]  # fmt: skip
    assert text["text_revision"]["body"] == TEXT  # the old text is kept


def test_old_must_occur_exactly_once(store):
    ref = human(store, "a cat, a cat and a dog")
    error = refused(store, "edit_page", page=ref["slug"], old="horse", new="x")
    assert "old is not in the page's body" in error
    error = refused(store, "edit_page", page=ref["slug"], old="a cat", new="x")
    assert "occurs 2 times" in error
    assert store.page(ref["slug"])["rev"] == 1  # nothing saved
    out = ok(store, "edit_page", page=ref["slug"], old="a cat", new="a bird",
             replace_all=True)  # fmt: skip
    assert out["replacements"] == 2
    assert store.page(ref["slug"])["body"] == "a bird, a bird and a dog"
    ok(store, "edit_page", page=ref["slug"], old=" and a dog", new="")  # delete
    assert store.page(ref["slug"])["body"] == "a bird, a bird"


def test_bad_requests_are_refused(store):
    ref = human(store, TEXT)
    for args, error in [
        ({}, "nothing to change"),
        ({"old": "milk"}, "give both old and new"),
        ({"new": "milk"}, "give both old and new"),
        ({"old": "milk", "new": "x", "body": "y", "rev": 1}, "not both"),
        ({"body": "everything new"}, "needs rev"),
        ({"old": "", "new": "x"}, "old must not be empty"),
        ({"title": "  "}, "title must not be empty"),
        ({"old": "milk", "new": "x\x00"}, "NUL"),
    ]:
        assert error in refused(store, "edit_page", page=ref["slug"], **args), args
    assert "no such page" in refused(store, "edit_page", page="nope", title="x")
    assert store.page(ref["slug"])["rev"] == 1


def test_a_stale_rev_is_refused(store):
    ref = human(store, TEXT)
    ok(store, "edit_page", page=ref["slug"], old="bread", new="rolls", rev=1)
    for args in [
        {"old": "milk", "new": "x", "rev": 1},
        {"body": "all new", "rev": 1},
        {"title": "New", "rev": 1},
    ]:
        error = refused(store, "edit_page", page=ref["slug"], **args)
        assert "the page has changed: it is at rev 2" in error, args
    assert store.page(ref["slug"])["body"].endswith("rolls")


def test_whole_body_with_the_current_rev_and_a_title(store):
    ref = human(store, TEXT)
    out = ok(store, "edit_page", page=ref["slug"], body="all new\r\ntext", rev=1,
             title="  Renamed   list ")  # fmt: skip
    assert (out["title_before"], out["title"]) == ("Shopping list", "Renamed list")
    p = store.page(ref["slug"])
    assert (p["title"], p["body"], p["rev"]) == ("Renamed list", "all new\ntext", 2)


def test_dry_run_writes_nothing(store):
    ref = human(store, TEXT)
    before = store.page(ref["slug"])
    out = ok(store, "edit_page", page=ref["slug"], old="eggs", new="ham", dry_run=True)
    assert out["dry_run"] and out["changed"] and out["rev"] == 1
    assert "+milk and ham" in out["diff"]
    after = store.page(ref["slug"])
    assert (after["body"], after["rev"], after["updated_at"]) == (
        before["body"], before["rev"], before["updated_at"],
    )  # fmt: skip
    assert revs(store, ref["slug"]) == [1]


def test_an_edit_that_changes_nothing_is_no_revision(store):
    ref = human(store, TEXT)
    out = ok(store, "edit_page", page=ref["slug"], old="milk", new="milk")
    assert not out["changed"] and out["rev"] == 1 and out["diff"] == ""
    assert revs(store, ref["slug"]) == [1]


def test_edits_of_a_trashed_page_are_refused(store):
    ref = human(store, TEXT)
    store.delete_page(ref["slug"])
    assert "no such page" in refused(
        store, "edit_page", page=ref["slug"], old="milk", new="x"
    )
    assert "no such page" in refused(store, "revert", page=ref["slug"], to_rev=1, rev=1)


def test_revert_to_rev_restores_as_a_new_revision(store):
    ref = human(store, TEXT)
    ok(store, "edit_page", page=ref["slug"], old="milk", new="oat milk",
       title="Groceries")  # fmt: skip
    dry = ok(store, "revert", page=ref["slug"], to_rev=1, dry_run=True)
    assert dry["dry_run"] and dry["rev"] == 2 and dry["restores"] == 1
    assert "-oat milk and eggs\n+milk and eggs\n" in dry["diff"]
    assert store.page(ref["slug"])["rev"] == 2
    assert "give rev" in refused(store, "revert", page=ref["slug"], to_rev=1)
    out = ok(store, "revert", page=ref["slug"], to_rev=1, rev=2)
    assert (out["rev_before"], out["rev"], out["folded"]) == (2, 3, None)
    p = store.page(ref["slug"])
    assert (p["body"], p["title"]) == (TEXT, "Groceries")  # title kept
    assert revs(store, ref["slug"]) == [3, 2, 1]  # history kept: nothing rewritten
    # the revert can itself be reverted, and the title restored with it
    ok(store, "revert", page=ref["slug"], to_rev=2, rev=3)
    assert store.page(ref["slug"])["body"] == "Shopping list\noat milk and eggs\nbread"
    ok(store, "revert", page=ref["slug"], to_rev=1, rev=4, restore_title=True)
    assert store.page(ref["slug"])["title"] == "Shopping list"


def test_revert_to_rev_checks_the_current_rev_and_the_target(store):
    ref = human(store, TEXT)
    ok(store, "edit_page", page=ref["slug"], old="milk", new="tea")
    error = refused(store, "revert", page=ref["slug"], to_rev=1, rev=1)
    assert "the page has changed: it is at rev 2" in error
    error = refused(store, "revert", page=ref["slug"], to_rev=9, rev=2)
    assert "no such revision 9" in error
    same = ok(store, "revert", page=ref["slug"], to_rev=2, rev=2)
    assert not same["changed"] and same["rev"] == 2  # already so: no revision


def test_quick_edits_fold_into_one_revision_with_a_new_number(store):
    ref = human(store, TEXT)
    one = ok(store, "edit_page", page=ref["slug"], old="milk", new="tea", rev=1)
    two = ok(store, "edit_page", page=ref["slug"], old="bread", new="jam", rev=2)
    assert (one["rev"], two["rev"], two["folded"]) == (2, 3, 2)
    # one revision for the burst; its number moved on, leaving a gap
    assert revs(store, ref["slug"]) == [3, 1]
    assert store.page(ref["slug"])["rev"] == 3
    # the burst's revision keeps when it started
    with closing(connect(store.db)) as conn:
        created = conn.execute(
            "SELECT created_at FROM page_rev WHERE page_id = ? AND rev = 3",
            (ref["page_id"],),
        ).fetchone()[0]
    assert created <= store.page(ref["slug"])["updated_at"]


def test_edits_outside_the_window_or_after_another_are_new_revisions(store):
    ref = human(store, TEXT)
    ok(store, "edit_page", page=ref["slug"], old="milk", new="tea")
    age(store, ref["page_id"])
    out = ok(store, "edit_page", page=ref["slug"], old="bread", new="jam")
    assert (out["rev"], out["folded"]) == (3, None)
    # the user edits in the PWA: Claude's next edit does not fold over theirs
    store.update_page(ref["slug"], 3, None, "user text", "giles@example.com")
    out = ok(store, "edit_page", page=ref["slug"], old="user", new="their")
    assert (out["rev"], out["folded"]) == (5, None)
    assert revs(store, ref["slug"]) == [5, 4, 3, 2, 1]


def test_no_folding_into_the_first_revision_or_a_revert(store):
    w = write(store, body="draft")  # rev 1 by Claude: never folded into
    out = ok(store, "edit_page", page=w["slug"], old="draft", new="final")
    assert (out["rev"], out["folded"]) == (2, None)
    ref = human(store, TEXT)
    ok(store, "edit_page", page=ref["slug"], old="milk", new="tea")
    back = ok(store, "revert", page=ref["slug"], to_rev=1, rev=2)
    assert (back["rev"], back["folded"]) == (3, None)  # a revert never folds
    after = ok(store, "edit_page", page=ref["slug"], old="bread", new="jam")
    assert (after["rev"], after["folded"]) == (4, None)  # nor is folded into
    assert revs(store, ref["slug"]) == [4, 3, 2, 1]


def test_a_revert_keeping_a_new_title_is_not_folded_into(store):
    """The revert's (title, body) pair is new when it keeps a title changed since:
    it is still a revert, by its body."""
    ref = human(store, TEXT)
    ok(store, "edit_page", page=ref["slug"], old="milk", new="tea", title="T2")
    age(store, ref["page_id"])
    back = ok(store, "revert", page=ref["slug"], to_rev=1, rev=2)
    assert back["title"] == "T2" and back["rev"] == 3
    after = ok(store, "edit_page", page=ref["slug"], old="bread", new="jam")
    assert (after["rev"], after["folded"]) == (4, None)
    assert revs(store, ref["slug"]) == [4, 3, 2, 1]


def test_overlapping_matches_are_refused(store):
    ref = human(store, "xaaay")
    error = refused(store, "edit_page", page=ref["slug"], old="aa", new="b")
    assert "overlapping itself" in error
    error = refused(store, "edit_page", page=ref["slug"], old="aa", new="b",
                    replace_all=True)  # fmt: skip
    assert "overlapping itself" in error
    assert store.page(ref["slug"])["rev"] == 1
    # a self-overlapping old that occurs once, or apart, is fine
    ok(store, "edit_page", page=ref["slug"], old="aaa", new="aba")
    assert store.page(ref["slug"])["body"] == "xabay"
    other = human(store, "aa-aa")
    out = ok(store, "edit_page", page=other["slug"], old="aa", new="b",
             replace_all=True)  # fmt: skip
    assert out["replacements"] == 2 and store.page(other["slug"])["body"] == "b-b"


def test_a_replacement_over_the_page_limit_is_refused_before_it_is_built(
    store, monkeypatch
):
    """1 MB of one letter, each replaced by 200 kB, would be 200 GB: refused from
    the count alone, without building it (str.replace would never return)."""
    ref = human(store, "seed")
    with closing(connect(store.db)) as conn:
        conn.execute(
            "UPDATE page SET body = ? WHERE id = ?", ("a" * 999_000, ref["page_id"])
        )
    calls = []
    real = mcp_server.replaced

    def spy(body, old, new, every):
        calls.append(len(body))
        return real(body, old, new, every)

    monkeypatch.setattr(editing, "replaced", spy)
    error = refused(store, "edit_page", page=ref["slug"], old="a",
                    new="b" * 200_000, replace_all=True)  # fmt: skip
    assert "the page text is 199,800,000,000 bytes" in error and calls == [999_000]
    assert store.page(ref["slug"])["body"] == "a" * 999_000
    # over by a little: refused; under: saved
    with closing(connect(store.db)) as conn:
        conn.execute(
            "UPDATE page SET body = ? WHERE id = ?",
            ("x" * 900_000 + "b", ref["page_id"]),
        )
    error = refused(store, "edit_page", page=ref["slug"], old="b", new="c" * 100_001)
    assert "the page text is 1,000,001 bytes" in error
    ok(store, "edit_page", page=ref["slug"], old="b", new="c" * 99_999)
    assert len(store.page(ref["slug"])["body"]) == 999_999


def test_emptying_a_page_needs_allow_empty(store):
    ref = human(store, TEXT)
    error = refused(store, "edit_page", page=ref["slug"], body="  \n", rev=1)
    assert "allow_empty" in error
    error = refused(store, "edit_page", page=ref["slug"], old=TEXT, new="")
    assert "allow_empty" in error
    assert store.page(ref["slug"])["rev"] == 1
    out = ok(store, "edit_page", page=ref["slug"], body="", rev=1, allow_empty=True)
    assert out["changed"] and store.page(ref["slug"])["body"] == ""
    # a title change on an empty page is not emptying it
    ok(store, "edit_page", page=ref["slug"], title="Empty")
    # restoring an empty text needs it too
    ok(store, "revert", page=ref["slug"], to_rev=1, rev=3)
    error = refused(store, "revert", page=ref["slug"], to_rev=3, rev=4)
    assert "allow_empty" in error
    ok(store, "revert", page=ref["slug"], to_rev=3, rev=4, allow_empty=True)
    assert store.page(ref["slug"])["body"] == ""


def test_a_window_of_0_never_folds(store):
    store.window = 0
    ref = human(store, TEXT)
    ok(store, "edit_page", page=ref["slug"], old="milk", new="tea")
    ok(store, "edit_page", page=ref["slug"], old="bread", new="jam")
    assert revs(store, ref["slug"]) == [3, 2, 1]


def test_folding_keeps_the_web_editors_conflict(tmp_path):
    """rev is the PWA's edit token: an editor that loaded Claude's first edit of a
    burst must get a 409 once the burst moves on, never overwrite it silently."""
    client = TestClient(create_app(tmp_path / "data"))
    store = Store(tmp_path / "data")
    ref = human(store, TEXT)
    url = f"/api/pages/{ref['page_id']}"
    ok(store, "edit_page", page=ref["slug"], old="milk", new="tea")
    loaded = client.get(url).json()["rev"]
    assert loaded == 2
    out = ok(store, "edit_page", page=ref["slug"], old="bread", new="jam")
    assert out["folded"] == 2  # rev 2 is gone; the page is at 3
    stale = client.patch(url, json={"base_rev": loaded, "body": "mine"})
    assert stale.status_code == 409
    assert store.page(ref["slug"])["body"] == "Shopping list\ntea and eggs\njam"
    fresh = client.patch(url, json={"base_rev": 3, "body": "mine"})
    assert fresh.status_code == 200 and fresh.json()["rev"] == 4
    # Claude's next edit, within the window, does not fold over the user's
    out = ok(store, "edit_page", page=ref["slug"], old="mine", new="ours", rev=4)
    assert (out["rev"], out["folded"]) == (5, None)


def test_claude_edited_marker_and_search(store):
    mine = human(store, "untouched words")
    edited = human(store, "edited words")
    own = write(store, title="Claude page", body="claude words")
    ok(store, "edit_page", page=edited["slug"], old="edited", new="changed")

    def found(query):
        return {r["slug"] for r in ok(store, "search", query=query)["results"]}

    assert found("is:claude-edited") == {edited["slug"]}
    assert edited["slug"] in found("words -is:claude")
    assert found("words -is:claude-edited") == {mine["slug"], own["slug"]}
    page = ok(store, "read", page=edited["slug"])["page"]
    assert page["edited_by_claude"] and not page["written_by_claude"]
    assert not ok(store, "read", page=mine["slug"])["page"]["edited_by_claude"]
    # an append to Claude's own page changes its text over MCP too
    ok(store, "write", title="", body="more", origin="", append_to=own["id"])
    assert found("is:claude-edited") == {edited["slug"], own["slug"]}


def test_the_switch_turns_content_editing_off(store, monkeypatch):
    assert {"edit_page", "revert"} <= set(tools(store))
    for off in ("0", "false", "Off"):
        monkeypatch.setenv("SCRAP_MCP_CONTENT_EDIT", off)
        names = set(tools(store))
        assert "edit_page" not in names
        assert {"write", "edit_meta", "revert", "revisions"} <= names
        ref = human(store, TEXT)
        error = refused(store, "revert", page=ref["slug"], to_rev=1, dry_run=True)
        assert "text editing is off" in error
    ref = human(store, TEXT)
    error = refused(store, "edit_page", page=ref["slug"], old="milk", new="x")
    assert "edit_page" in error  # an unknown tool
    assert store.page(ref["slug"])["rev"] == 1
    monkeypatch.setenv("SCRAP_MCP_CONTENT_EDIT", "1")
    assert "edit_page" in tools(store)
    for bad in ("maybe", "", "  "):  # set but empty: not on unasked
        monkeypatch.setenv("SCRAP_MCP_CONTENT_EDIT", bad)
        with pytest.raises(SystemExit, match="SCRAP_MCP_CONTENT_EDIT"):
            mcp_server.server(store)


def test_instructions_follow_the_switch(store, monkeypatch):
    on = mcp_server.server(store).instructions or ""
    assert "only on a page the user asked you to\nchange" in on
    monkeypatch.setenv("SCRAP_MCP_CONTENT_EDIT", "0")
    off = mcp_server.server(store).instructions or ""
    assert "edit_page" not in off and "No tool changes the text" in off


def test_no_mcp_path_deletes_a_page_or_writes_text_without_a_revision(store):
    """Every tool and argument: nothing deletes or trashes a page; only write (new
    pages and appends), edit_page and revert(to_rev) take text, and every text change
    they make is a revision; a whole body needs the current rev."""
    names = tools(store)
    # the trash can be listed and a page brought back, never emptied or deleted
    risky = {n for n in names if re.search("delete|trash|purge|remove|empty", n)}
    assert risky == {"trash", "undelete"}
    for name, args in names.items():
        if name not in ("write", "edit_page"):
            assert not args & {"body", "title", "text", "fields", "status"}, name
    ref = human(store, TEXT)
    assert "needs rev" in refused(store, "edit_page", page=ref["slug"], body="x")
    ok(store, "edit_page", page=ref["slug"], old="milk", new="tea")
    ok(store, "edit_page", page=ref["slug"], title="New title")
    ok(store, "revert", page=ref["slug"], to_rev=1, rev=3, restore_title=True)
    ok(store, "edit_meta", pages=[ref["slug"]], kind="todo")
    with closing(connect(store.db)) as conn:
        rows = conn.execute(
            "SELECT rev, title, body FROM page_rev WHERE page_id = ? ORDER BY rev",
            (ref["page_id"],),
        ).fetchall()
        deleted = conn.execute(
            "SELECT deleted_at FROM page WHERE id = ?", (ref["page_id"],)
        ).fetchone()[0]
    p = store.page(ref["slug"])
    # the page's text is always its latest revision's; nothing went to the trash
    assert (rows[-1]["title"], rows[-1]["body"]) == (p["title"], p["body"])
    assert rows[-1]["rev"] == p["rev"] and deleted is None
    assert rows[0]["body"] == TEXT  # the first is never folded away


@pytest.mark.timing  # run alone: see conftest.py
def test_overlap_checks_are_linear_in_the_page():
    """A long self-overlapping old on a large page: the check scans each match's own
    span once (it runs holding the write lock), so these take milliseconds, not the
    minutes a scan of every start would."""
    body = "a" * 999_000
    begin = time.monotonic()
    for old in ("a" * 100_000, "a" * 10_000, "aa"):
        assert mcp_server.overlapping(body, old)
    assert mcp_server.overlapping("ab" * 499_000, "ab" * 50_000)
    for old in ("a" * 100_000 + "b", "ba"):
        assert not mcp_server.overlapping(body + "b", old)
    assert not mcp_server.overlapping("xaay-xaay" * 50_000, "aa")
    assert mcp_server.overlapping("xaay" * 50_000 + "aaa", "aa")
    assert time.monotonic() - begin < 3  # generous: ~0.1 s here


@pytest.mark.timing  # run alone: see conftest.py
def test_a_long_overlapping_old_is_refused_quickly(store):
    ref = human(store, "seed")
    with closing(connect(store.db)) as conn:
        conn.execute(
            "UPDATE page SET body = ? WHERE id = ?", ("a" * 999_000, ref["page_id"])
        )
    begin = time.monotonic()
    for every in (False, True):
        error = refused(store, "edit_page", page=ref["slug"], old="a" * 100_000,
                        new="b", replace_all=every)  # fmt: skip
        assert "occurs 9 times" in error or "overlapping itself" in error
    assert time.monotonic() - begin < 10  # generous: well under a second here


def patched(diff: str, before: str) -> str:
    """Apply a unified diff to before, checking every context and removed line is at
    the line its hunk header says."""
    lines = mcp_server.split_lines(before)
    out, at = [], 0
    rows = mcp_server.split_lines(diff)[2:]
    i = 0
    while i < len(rows):
        head = mcp_server.HUNK.match(rows[i])
        assert head, rows[i]
        first, count = int(head[1]), int((head[2] or ",1")[1:])
        start = first - 1 if count else first
        out += lines[at:start]
        at = start
        i += 1
        while i < len(rows) and not rows[i].startswith("@@"):
            row = rows[i]
            if i + 1 < len(rows) and rows[i + 1].startswith("\\"):
                row = row[:-1]  # the text ended without a newline
                i += 1
            if row[0] in " -":
                assert lines[at] == row[1:], (at, row)
                at += 1
            if row[0] in " +":
                out.append(row[1:])
            i += 1
    return "".join(out + lines[at:])


@pytest.mark.timing  # run alone: see conftest.py
def test_the_diff_is_right_and_quick_on_large_pages():
    rng = random.Random(7)
    for _ in range(300):
        a = [rng.choice("abcde") for _ in range(rng.randint(0, 30))]
        b = list(a)
        for _ in range(rng.randint(1, 4)):
            at = rng.randint(0, len(b))
            if rng.random() < 0.5 and b:
                del b[min(at, len(b) - 1)]
            else:
                b.insert(at, rng.choice("abcdefg"))
        before, after = "\n".join(a), "\n".join(b)
        diff, cut = mcp_server.unified("p", 1, before, after)
        assert not cut and (diff == "") == (before == after)
        assert patched(diff, before) == after, (a, b)
    # whole-body replace of a large page: one hunk, quickly, and cut
    big = "\n".join(f"line {i} x" for i in range(60_000))
    other = "\n".join(f"row {i} y" for i in range(60_000))
    begin = time.monotonic()
    diff, cut = mcp_server.unified("p", 1, big, other)
    assert time.monotonic() - begin < 3 and cut
    assert diff.startswith("--- p (rev 1)\n+++ p (edited)\n@@ -1,60000 +1,60000 @@\n")
    big_diff, _ = mcp_server.unified("p", 1, big[:20_000], other[:20_000])
    assert patched(big_diff, big[:20_000]) == other[:20_000]
    # a small edit in a large page: difflib, on those lines only
    edited = big.replace("line 30000 x", "line 30000 z")
    diff, cut = mcp_server.unified("p", 1, big, edited)
    assert not cut and "@@ -29998,7 +29998,7 @@" in diff
    assert patched(diff, big) == edited


def test_the_diff_applies_with_git_apply(tmp_path):
    """Repeated blank lines and bullets (where difflib matches inside a slice
    differently) still give a diff with full trailing context that git apply takes,
    and a form feed does not split a line."""
    rng = random.Random(160)
    for _n in range(300):
        a = [
            rng.choice(["", "- x", "- y", "para", "\x0c"])
            for _ in range(rng.randint(5, 40))
        ]
        b = list(a)
        for _ in range(rng.randint(1, 3)):
            at = rng.randint(0, len(b))
            if rng.random() < 0.5 and b:
                del b[min(at, len(b) - 1)]
            else:
                b.insert(at, rng.choice(["", "- x", "- y", "new"]))
        before, after = "\n".join(a) + "\n", "\n".join(b) + "\n"
        diff, _ = mcp_server.unified("p", 1, before, after)
        if before == after:
            assert diff == ""
            continue
        assert "No newline" not in diff, (a, b)
        (tmp_path / "p").write_bytes(before.encode())
        body = diff.split("\n", 2)[2]  # git apply wants plain file names
        (tmp_path / "d.patch").write_bytes(f"--- p\n+++ p\n{body}".encode())
        run = subprocess.run(
            ["git", "apply", "-p0", "d.patch"],
            cwd=tmp_path, capture_output=True, text=True,
        )  # fmt: skip
        assert run.returncode == 0, (a, b, diff, run.stderr)
        assert (tmp_path / "p").read_bytes().decode() == after


def test_the_diff_splits_lines_on_newline_only():
    diff, _ = mcp_server.unified("p", 1, "a\x0cb\nc", "a\x0cb\nd")
    assert diff.count("\n\\ No newline") == 2 and " a\x0cb\n" in diff


def enrich_jobs(store) -> list[tuple[str, str, str]]:
    with closing(connect(store.db)) as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT page_id, reason, state FROM enrich_job ORDER BY id"
        )]  # fmt: skip


def test_text_edits_queue_enrichment_like_a_pwa_save(store, monkeypatch):
    """edit_page and revert(to_rev) saves queue one debounced enrich job (the summary
    and related pages follow the new text), none with enrichment off; a burst
    moves that one job on, it does not add more."""
    monkeypatch.setenv("SCRAP_INGEST", "off")
    ref = human(store, TEXT)  # no job: enrichment is off
    ok(store, "edit_page", page=ref["slug"], old="milk", new="tea")
    assert enrich_jobs(store) == []
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH_DEBOUNCE", "3600")
    ok(store, "edit_page", page=ref["slug"], old="bread", new="jam")
    assert enrich_jobs(store) == [(ref["page_id"], "save", "queued")]
    ok(store, "edit_page", page=ref["slug"], old="jam", new="honey")  # a burst
    ok(store, "edit_page", page=ref["slug"], title="Groceries")
    assert enrich_jobs(store) == [(ref["page_id"], "save", "queued")]
    with closing(connect(store.db)) as conn:
        conn.execute("DELETE FROM enrich_job")
    rev = store.page(ref["slug"])["rev"]
    ok(store, "revert", page=ref["slug"], to_rev=1, rev=rev, dry_run=True)
    assert enrich_jobs(store) == []  # a dry run queues nothing
    ok(store, "revert", page=ref["slug"], to_rev=1, rev=rev)
    assert enrich_jobs(store) == [(ref["page_id"], "save", "queued")]
    monkeypatch.setenv("SCRAP_ENRICH", "off")
    with closing(connect(store.db)) as conn:
        conn.execute("DELETE FROM enrich_job")
    ok(store, "edit_page", page=ref["slug"], old="milk", new="oat milk")
    assert enrich_jobs(store) == []


def test_unified_matches_difflib_on_varied_inputs():
    """The diff is what difflib makes of the whole text (lines distinct, so trimming
    the common start and end cannot change how they match)."""
    rng = random.Random(178)
    for _n in range(400):
        a = [f"line {i}\n" for i in range(rng.randint(0, 60))]
        b = list(a)
        for _ in range(rng.randint(0, 6)):
            at = rng.randint(0, len(b))
            roll = rng.random()
            if roll < 0.35 and b:
                del b[min(at, len(b) - 1)]
            elif roll < 0.7 and b:
                b[min(at, len(b) - 1)] = f"changed {rng.random()}\n"
            else:
                b.insert(at, f"new {rng.random()}\n")
        before, after = "".join(a), "".join(b)
        expected = "".join(
            difflib.unified_diff(a, b, "p (rev 1)", "p (edited)", n=mcp_server.CONTEXT)
        )
        diff, cut = mcp_server.unified("p", 1, before, after)
        assert not cut
        assert diff == expected, (a, b)
