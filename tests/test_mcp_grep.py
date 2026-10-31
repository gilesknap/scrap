"""MCP search's grep (#474): raw text matched as a substring or a regex, narrowed by
the query, with matching lines; the trash left out and the guards."""

import random
import string
import time

import pytest

from scrap.ingest import put_derived
from scrap.store import Store, now
from scrap.store import grep as greps
from scrap.store.errors import InvalidError
from test_mcp import human, ok, refused, write

TABLE = "Intro\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def found(store, **args) -> list[dict]:
    return ok(store, "search", **args)["results"]


def test_substring_ignores_case_and_punctuation_counts(store):
    table = write(store, title="Table", body=TABLE)
    write(store, title="Prose", body="a b c, plain words")
    [row] = found(store, grep="|---|")
    assert row["id"] == table["id"] and row["title"] == "Table"
    assert row["match_count"] == 1
    assert row["matches"] == [{"in": "body", "line": 4, "text": "|---|---|"}]
    assert [r["id"] for r in found(store, grep="TABLE")] == [table["id"]]  # its title
    assert found(store, grep="table")[0]["matches"][0] == {
        "in": "title", "line": 1, "text": "Table"
    }  # fmt: skip


def test_regex_lines_are_numbered_per_line(store):
    write(store, title="Cmds", body="first\nkubectl -n scrap exec a\nmid\nkubectl -n x")
    [row] = found(store, grep=r"^kubectl -n \w+", regex=True)
    assert [(m["line"], m["text"]) for m in row["matches"]] == [
        (2, "kubectl -n scrap exec a"), (4, "kubectl -n x"),
    ]  # fmt: skip
    assert row["match_count"] == 2
    assert found(store, grep="^KUBECTL", regex=True) == []  # a regex keeps case
    # without regex, ^ is a character
    assert found(store, grep="^kubectl") == []


def test_the_table_example(store):
    table = write(store, title="T", body=TABLE)
    write(store, title="Rule", body="a\n\n---\n\nb")  # a rule is ---, at a line start
    hits = found(store, grep=r"^\|?\s*:?-{3,}:?\s*\|", regex=True)
    assert [r["id"] for r in hits] == [table["id"]]


def test_the_query_narrows_and_orders(store):
    note = write(store, title="N", body="ip 10.0.0.1", tags=["net"])
    todo = write(store, title="Do", body="ping 10.0.0.1", kind="todo")
    write(store, title="Other", body="10x0y0z1", tags=["net"])  # dots are dots
    assert [r["id"] for r in found(store, grep="10.0.0.1")] == [todo["id"], note["id"]]
    assert [r["id"] for r in found(store, query="kind:todo", grep="10.0.0.1")] == [
        todo["id"]
    ]
    assert [r["id"] for r in found(store, query="tag:net", grep="10.0.0.1")] == [
        note["id"]
    ]
    assert [r["id"] for r in found(store, query="ping", grep="10.0.0")] == [todo["id"]]
    assert found(store, query="kind:todo", grep="ip 10") == []


def test_the_trash_is_never_scanned(store):
    page = write(store, title="Gone", body="needle_here(")
    assert len(found(store, grep="needle_here(")) == 1
    store.delete_page(page["id"])
    assert found(store, grep="needle_here(") == []


def test_a_files_text_matches(store):
    ref = human(store, "Minutes")
    cid = store.page(ref["page_id"])["captures"][0]["id"]
    with store.connect() as conn:
        put_derived(conn, cid, "ab" * 32, "ocr", "pypdf", now(),
                    text="page one\nbudget: $1,200.50\nend")  # fmt: skip
    [row] = found(store, grep="$1,200.50")
    assert row["id"] == ref["page_id"]
    assert row["matches"] == [
        {"in": "file", "sha256": "ab" * 32, "line": 2, "text": "budget: $1,200.50"}
    ]


def test_long_lines_are_cut_around_the_match(store):
    write(store, title="Long", body="x" * 1000 + "MARK" + "y" * 1000)
    [row] = found(store, grep="mark")
    text = row["matches"][0]["text"]
    assert "MARK" in text and text.startswith("…") and text.endswith("…")
    assert len(text) <= greps.LINE + 2


def test_lines_returned_and_counted_are_capped(store, monkeypatch):
    monkeypatch.setattr(greps, "MAX_COUNT", 7)
    write(store, title="Many", body="\n".join(f"hit {n} hit" for n in range(20)))
    [row] = found(store, grep="hit")
    assert len(row["matches"]) == greps.MAX_LINES and row["match_count"] == 7
    assert [m["line"] for m in row["matches"]] == [1, 2, 3, 4, 5]  # once a line


def test_paging(store):
    ids = [write(store, title=f"P{n}", body="same_text")["id"] for n in range(5)]
    newest = ids[::-1]
    assert [r["id"] for r in found(store, grep="same_text", limit=2)] == newest[:2]
    got = ok(store, "search", grep="same_text", limit=2, offset=2)
    assert [r["id"] for r in got["results"]] == newest[2:4] and got["offset"] == 2
    assert [r["id"] for r in found(store, grep="same_text", offset=4)] == newest[4:]


def test_refusals(store):
    write(store, title="T", body="text")
    assert "invalid regex: missing ): (unclosed" in refused(
        store, "search", grep="(unclosed", regex=True
    )
    assert "regex needs grep" in refused(store, "search", regex=True)
    too_long = "a" * (greps.MAX_PATTERN + 1)
    assert "200" in refused(store, "search", grep=too_long)
    assert found(store, grep="(unclosed") == []  # a substring: no regex to refuse


def test_the_scan_has_a_time_budget(store, monkeypatch):
    monkeypatch.setattr(greps, "SECONDS", -1)  # spent before it starts
    write(store, title="T", body="text")
    assert "took over -1 seconds" in refused(store, "search", grep="text")


@pytest.mark.parametrize(
    "pattern, text",
    [  # once near-quadratic: each line's search re-read the rest of the text
        (r"(?s)(?:a|b|\n)*a(?:a|b|\n){999}", "".join(
            random.Random(1).choice("ab\n" if i % 50 else "\n") for i in range(8000)
        )),
        (r"(?:(\w)|(\s)){1,999}", "".join(  # captures, which RE2 need not track
            random.Random(1).choice(string.ascii_lowercase + " \n")
            for _ in range(100_000)
        )),
    ],
)  # fmt: skip
def test_a_costly_regex_ends_within_the_budget(pattern, text):
    pat = greps.compile_pattern(pattern, True)
    start = time.monotonic()
    try:
        _, count = greps.scan(pat, text, {}, start + greps.SECONDS)
        assert count >= 1
    except InvalidError as e:
        assert "took over" in str(e)
    assert time.monotonic() - start < greps.SECONDS + 2


def test_a_long_text_is_searched_in_windows(monkeypatch):
    monkeypatch.setattr(greps, "WINDOW", 10)
    pat = greps.compile_pattern("x", False)
    text = "\n".join(["aaaa"] * 30 + ["xx", "a", "x"] + ["aaaa"] * 30) + "\n"
    found, count = greps.scan(pat, text, {}, time.monotonic() + 10)
    assert count == 2 and [m["line"] for m in found] == [31, 33]
    # a match longer than a window is missed
    assert greps.scan(greps.compile_pattern("(?s)a{4}.a{4}.a{4}.a{4}", True),
                      "aaaa\n" * 4, {}, time.monotonic() + 10)[1] == 0  # fmt: skip


def test_a_compile_bomb_is_refused_quickly(store):
    write(store, title="T", body="a" * 50)
    start = time.monotonic()
    for bomb in ("(((a{1000}){1000}){1000})", "((a{999}){999}){999}",
                 "(((a{100}){100}){100})", "((((a{30}){30}){30}){30})"):  # fmt: skip
        assert "invalid regex" in refused(store, "search", grep=bomb, regex=True)
    assert time.monotonic() - start < 5


def test_re2_refuses_what_it_cannot_do(store):
    write(store, title="T", body="abab")
    assert "invalid regex" in refused(store, "search", grep=r"(ab)\1", regex=True)
    assert "invalid regex" in refused(store, "search", grep="a(?=b)", regex=True)


def test_case_in_a_regex(store):
    page = write(store, title="T", body="Hello World")
    assert found(store, grep="hello", regex=True) == []
    [row] = found(store, grep="(?i)hello", regex=True)
    assert row["id"] == page["id"]


def test_no_phantom_line_after_a_final_newline(store):
    write(store, title="T", body="a\nb\n")
    [row] = found(store, grep="^", regex=True)
    body = [m for m in row["matches"] if m["in"] == "body"]
    assert [(m["line"], m["text"]) for m in body] == [(1, "a"), (2, "b")]
    assert row["match_count"] == 3  # the title, and two lines of the body


def test_a_query_of_nothing_finds_nothing(store):
    write(store, title="T", body="text")
    assert found(store, query="!", grep="text") == []
    assert found(store, query='""', grep="text") == []


def test_the_query_orders_sort_group_and_rank(store):
    a = write(store, title="Bravo", body="zz_mark and wombat", kind="todo")
    b = write(store, title="Alpha", body="zz_mark", kind="note")
    c = write(store, title="Wombat facts", body="zz_mark")  # newest
    ids = lambda **kw: [r["id"] for r in found(store, grep="zz_mark", **kw)]  # noqa: E731
    assert ids() == [c["id"], b["id"], a["id"]]  # newest changed first
    assert ids(query="sort:title") == [b["id"], a["id"], c["id"]]
    assert ids(query="-sort:created") == [a["id"], b["id"], c["id"]]
    # group:type puts the pages in the app's sections: todos and notes apart
    assert ids(query="group:type") == [
        r["id"] for r in ok(store, "search", query="group:type")["results"]
    ]
    # ranked: the title match first, though the todo is older
    assert ids(query="wombat") == [c["id"], a["id"]]


def test_superseded_and_trashed_file_text_is_not_scanned(store):
    ref = human(store, "Minutes")
    cid = store.page(ref["page_id"])["captures"][0]["id"]
    with store.connect() as conn:
        put_derived(conn, cid, "ab" * 32, "ocr", "pypdf", now(), text="old_words")
        put_derived(conn, cid, "ab" * 32, "ocr", "pypdf", now(), text="new_words")
    assert found(store, grep="old_words") == []
    assert len(found(store, grep="new_words")) == 1
    store.delete_page(ref["page_id"])
    assert found(store, grep="new_words") == []


def test_several_files_sum_their_counts(store):
    ref = human(store, "kiwi title\nkiwi body\nand kiwi again")
    cid = store.page(ref["page_id"])["captures"][0]["id"]
    with store.connect() as conn:
        for n, sha in enumerate(("aa" * 32, "bb" * 32)):
            put_derived(conn, cid, sha, "ocr", "pypdf", now(),
                        text=f"kiwi {n}\nnone\nkiwi kiwi {n}")  # fmt: skip
    [row] = found(store, grep="kiwi")
    assert row["match_count"] == 1 + 3 + 2 + 2  # title, body, each file's two lines
    assert [(m["in"], m.get("sha256"), m["line"]) for m in row["matches"]] == [
        ("title", None, 1), ("body", None, 1), ("body", None, 2), ("body", None, 3),
        ("file", "aa" * 32, 1),
    ]  # fmt: skip


def test_offset_past_the_last_hit(store):
    write(store, title="T", body="only_one")
    assert ok(store, "search", grep="only_one", offset=5) == {
        "results": [], "offset": 5
    }  # fmt: skip
