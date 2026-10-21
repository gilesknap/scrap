"""Search (#84): the query syntax, ranking, filters, facets, tags and the reindex."""

import time
from contextlib import closing
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from scrap.app import create_app
from scrap.query import SORTS, Filter, Term, bound, due, parse
from scrap.store import SORT_SQL, Store, connect, migrations, new_ulid, slug_base

# ---- the parser


def test_words_phrases_and_not():
    q = parse('garden -shed !"bird box" "quiet  corner" plan')
    assert q.terms == [
        Term("garden"),
        Term("shed", neg=True),
        Term("bird box", phrase=True, neg=True),
        Term("quiet corner", phrase=True),
        Term("plan"),
    ]
    # every word a prefix, wherever it stands; NOT words and phrases exact
    assert [q.fts(t) for t in q.terms] == [
        '"garden"*', '"shed"', '"bird box"', '"quiet corner"', '"plan"*'
    ]  # fmt: skip


def test_filters_keep_their_token_as_typed():
    q = parse('Kind:Todo tag:tech/epics -tag:"home  life" is:personal')
    assert q.terms == []
    assert q.filters == [
        Filter("kind", "todo", False, "Kind:Todo"),
        Filter("tag", "tech/epics", False, "tag:tech/epics"),
        Filter("tag", "home life", True, '-tag:"home  life"'),
        Filter("is", "personal", False, "is:personal"),
    ]


def test_image_filters_parse():
    q = parse("has:image -image:Photo mantis")
    assert q.terms == [Term("mantis")]
    assert q.filters == [
        Filter("has", "image", False, "has:image"),
        Filter("image", "photo", True, "-image:Photo"),
    ]


def test_what_is_not_a_term():
    assert parse('- ! & ? "" -"" kind: tag:""').terms == []
    assert parse("- ! kind: tag:").filters == []
    assert parse("foo:bar").terms == [Term("foo:bar")]  # not a key: a word
    assert parse("salt salt").terms == [Term("salt")]
    assert parse('"unclosed phrase').terms == [Term("unclosed phrase", phrase=True)]
    assert parse("a\x00b").terms == [Term("a"), Term("b")]


def test_parsing_is_linear():
    started = time.monotonic()
    for bad in ('"' * 200_000, "-" * 200_000, "!-" * 100_000, 'tag:"' * 50_000,
                "a:" * 100_000, " x" * 100_000, '-"a' * 70_000):  # fmt: skip
        parse(bad)
    assert time.monotonic() - started < 2
    assert len(parse(" ".join(f"w{n}" for n in range(999))).terms) == 16


# ---- the store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path)
    s.migrate()
    return s


def page(store, title, body="", tags=(), kind="note", **fields):
    stamp = f"2026-01-{len(store.slugs()) + 1:02d}T00:00:00.000Z"
    p = {
        "slug": f"{slug_base(title)}-{len(store.slugs())}", "title": title,
        "body": body, "kind": kind, "fields": fields, "tags": list(tags),
        "created_at": stamp, "updated_at": stamp,
    }  # fmt: skip
    return store.import_page(p, [(new_ulid(), "note", body, [])], "me")[0]


def slugs(store, query):
    return [h["slug"] for h in store.search(query, 20)]


def test_title_tags_and_summary_are_indexed_and_weigh_more(store):
    for n in range(10):  # most pages don't say kafka
        page(store, f"Other {n}", "a long body " * 20, tags=["misc"], summary="gist")
    body = page(store, "Notes", "we chose kafka over the rest kafka again")
    summary = page(store, "Event bus", "a long body " * 20, summary="kafka at work")
    tag = page(store, "Streams", "a long body " * 20, tags=["tech/kafka"])
    title = page(store, "Kafka", "a long body " * 20)
    assert slugs(store, "kafka") == [title, tag, summary, body]
    assert slugs(store, "streams kafka") == [tag]  # each word anywhere in the page
    assert slugs(store, "tech") == [tag]  # a tag's parts are words


def test_snippets_come_from_the_text(store):
    page(store, "Kafka", "about queues")
    assert store.search("kafka", 5)[0]["snippet"] == "about queues"
    assert store.search("queue", 5)[0]["snippet"] == "about <mark>queues</mark>"


def test_not_and_phrase(store):
    a = page(store, "Garden shed", "a bird box by the door")
    b = page(store, "Garden plan", "box hedge, bird bath")
    assert slugs(store, "garden") == [a, b] or slugs(store, "garden") == [b, a]
    assert slugs(store, "garden -shed") == [b]
    assert slugs(store, "garden !shed") == [b]
    assert slugs(store, '"bird box"') == [a]
    assert slugs(store, 'garden -"bird box"') == [b]
    assert slugs(store, "-shed") == [b]  # NOT alone: everything else, newest first
    assert slugs(store, "-garden") == []


def test_filters(store):
    todo = page(store, "Fix fence", kind="todo", status="open", personal=True,
                tags=["home/garden"])  # fmt: skip
    done = page(store, "Paint fence", kind="todo", status="done", personal=False,
                tags=["home"])  # fmt: skip
    read = page(store, "Fence book", kind="consume", tags=["books", "home/garden/diy"])
    assert set(slugs(store, "fence")) == {todo, done, read}
    assert slugs(store, "kind:todo") == [done, todo]  # filters alone: newest first
    assert set(slugs(store, "fence kind:read")) == {read}  # the PWA's name for it
    assert set(slugs(store, "fence kind:read kind:todo")) == {todo, done, read}
    assert set(slugs(store, "fence -kind:todo")) == {read}
    assert set(slugs(store, "tag:home")) == {todo, done, read}  # and its children
    assert set(slugs(store, "tag:garden")) == {todo, read}  # whole segments
    assert set(slugs(store, "tag:home/garden")) == {todo, read}
    assert slugs(store, "tag:gard") == []
    assert set(slugs(store, "tag:home -tag:books")) == {todo, done}
    assert slugs(store, "is:personal") == [todo]
    assert set(slugs(store, "is:work")) == {done, read}  # no personal field: work
    assert slugs(store, "is:done") == [done]
    assert set(slugs(store, "-is:personal")) == {done, read}
    assert slugs(store, "-is:done kind:todo") == [todo]
    assert slugs(store, "kind:nope") == slugs(store, "is:nope") == []


def test_snippet_of_a_filter_only_hit(store):
    page(store, "Plain", "[a link](https://x.example) then\x01 words", tags=["t"])
    page(store, "Summed", "body", tags=["t"], summary="the <gist>")
    hits = {h["title"]: h["snippet"] for h in store.search("tag:t", 5)}
    assert hits == {"Plain": "a link then words", "Summed": "the &lt;gist&gt;"}


def test_facets(store):
    page(store, "Fence one", kind="todo", personal=True, tags=["home/garden", "diy"])
    page(store, "Fence two", kind="todo", tags=["home/garden"])
    page(store, "Fence three", tags=["home", "books"])
    page(store, "Other", tags=["home"])
    f = store.facets("fence")
    assert f["total"] == 3
    assert f["kinds"] == [["todo", 2], ["note", 1]]
    assert f["personal"] == {"work": 2, "personal": 1}
    # home is on every hit: no narrowing; home/garden counts for home too
    assert f["tags"] == [["home/garden", 2], ["books", 1], ["diy", 1]]
    f = store.facets("fence -tag:books tag:home/garden")
    assert f["total"] == 2 and f["tags"] == [["diy", 1]]
    assert [a["token"] for a in f["active"]] == ["-tag:books", "tag:home/garden"]
    assert store.facets("")["total"] == 0
    one = store.facets("fence one")
    assert one["total"] == 1 and ["diy", 1] in one["tags"]  # a single hit: its tags


def test_tags_lists_live_pages_only(tmp_path):
    client = TestClient(create_app(tmp_path))
    store = Store(tmp_path)
    page(store, "A", tags=["x", "y/z"])
    gone = page(store, "B", tags=["x", "trashed"])
    store.delete_page(gone)
    page(store, "C", tags=["y/w", "y/z"])
    assert client.get("/api/tags").json() == [
        ["x", 1], ["y", 2], ["y/w", 1], ["y/z", 2]
    ]  # fmt: skip
    assert client.get("/api/search/facets", params={"q": "tag:x"}).json()["total"] == 1
    assert client.get("/tags").status_code in (200, 503)  # the PWA's route


def test_tag_and_summary_changes_reach_the_index(store):
    slug = page(store, "Plain page", "body")
    store.update_page(slug, None, None, None, "me", fields={"summary": "zebra cross"})
    assert slugs(store, "zebra") == [slug]
    store.update_page(slug, None, None, None, "me", fields={"summary": None})
    assert slugs(store, "zebra") == []


def test_migration_3_reindexes_existing_pages(tmp_path):
    """A database from before 0003: its pages' title, tags and summary are indexed."""
    db = tmp_path / "scrap.db"
    with closing(connect(db)) as conn:
        script = "".join(migrations()[:2])
        conn.executescript(f"BEGIN; {script} PRAGMA user_version = 2; COMMIT;")
        conn.execute(
            "INSERT INTO page (id, slug, title, body, fields, created_at, updated_at)"
            " VALUES ('P', 'p', 'Heading', 'Heading\n\nbody',"
            " '{\"summary\": \"gist\"}', 'x', 'x')"
        )
        conn.execute("INSERT INTO tag VALUES ('P', 'tech/epics')")
        conn.execute("INSERT INTO chunk (page_id, ord, text) VALUES ('P', 0, 'old')")
    store = Store(tmp_path)
    store.migrate()
    for word in ("epics", "gist", "body", "heading"):
        assert slugs(store, word) == ["p"]
    assert slugs(store, "old") == []
    with closing(connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
        row = conn.execute("SELECT title, tags, summary FROM chunk").fetchone()
        assert tuple(row) == ("Heading", "tech/epics", "gist")


def test_every_word_is_a_prefix_wherever_filters_stand(store):
    a = page(store, "Vscode setup", "devcontainers and podman")
    page(store, "Vscode todo", "devcontainers", kind="todo")
    for q in ("vsc kind:note", "kind:note vsc", "vsc kind:note dev",
              "kind:note dev vsc", "dev kind:note vsc pod"):  # fmt: skip
        assert slugs(store, q) == [a], q
    assert len(slugs(store, "vsc dev")) == 2  # two prefixes
    assert slugs(store, '"vsc"') == []  # a phrase is exact
    assert slugs(store, "vscode -devcontainers") == []
    assert len(slugs(store, "vscode -dev")) == 2  # a NOT word is exact


def test_prefix_words_keep_the_title_tier(store):
    body = page(store, "Notes", "vscode vscode vscode")
    for n in range(5):
        page(store, f"Other {n}", "a long body " * 20)
    title = page(store, "Vscode tips", "a long body " * 20)
    assert slugs(store, "vsc") == [title, body]


def test_date_bounds():
    now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    assert bound("after", "2026-03-01") == "2026-03-01"  # from the day's start
    assert bound("before", "2026-03-01") == "2026-03-02"  # to its end
    assert bound("after", "1w", now) == "2026-10-13T12:00:00.000Z"
    assert bound("after", "w", now) == bound("after", "1w", now)
    assert bound("before", "2m", now) == "2026-08-21T12:00:00.000Z"
    assert bound("after", "1y", now) == "2025-10-20T12:00:00.000Z"
    assert bound("after", "3d", now) == "2026-10-17T12:00:00.000Z"
    assert bound("before", "9999-12-31") == "~"  # past every timestamp
    assert bound("after", "0001-01-01") == "0001-01-01"
    for bad in ("2026-13-01", "2026/03/01", "0w", "101y", "-1w", "1x", "", "1.5w",
                "99999999d", "0d", "9" * 5000 + "d",
                "２w", "x" * 10_000):  # fmt: skip
        assert bound("after", bad, now) is None, bad
    q = parse("after:1w Before:2026-01-31 date:created -after:x")
    assert [(f.key, f.value, f.neg) for f in q.filters] == [
        ("after", "1w", False), ("before", "2026-01-31", False),
        ("date", "created", False), ("after", "x", True),
    ]  # fmt: skip


def test_date_filters(store):
    old = page(store, "Plan old")  # created and edited 2026-01-01
    mid = page(store, "Plan mid")  # 2026-01-02
    new = page(store, "Plan new")  # 2026-01-03, edited just now
    recent = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    with store.connect() as conn:
        conn.execute("UPDATE page SET updated_at = ? WHERE slug = ?", (recent, new))
    assert slugs(store, "after:1w") == [new]  # filters alone: newest first
    assert slugs(store, "plan after:1w") == [new]
    assert set(slugs(store, "plan before:1w")) == {old, mid}
    assert slugs(store, "plan -after:1w before:2026-01-01") == [old]  # days included
    assert set(slugs(store, "after:2026-01-02 before:2026-01-02 date:created")) == {mid}
    assert set(slugs(store, "plan after:2026-01-02 date:created")) == {mid, new}
    assert slugs(store, "plan after:2026-01-03 before:2026-01-31") == []  # edited later
    assert slugs(store, "plan after:2026-01-03 date:created") == [new]
    assert slugs(store, "plan after:soon") == []  # not a date: nothing
    assert len(slugs(store, "plan -after:soon")) == 3  # and with -, everything
    for q, n in [("before:9999-12-31", 3), ("after:9999-12-31", 0),
                 ("after:0001-01-01", 3), ("before:0001-01-01", 0),
                 ("after:99999999d", 0), ("before:0d", 0), ("-before:0d", 3),
                 ("after:" + "9" * 5000 + "d", 0)]:  # fmt: skip
        assert len(slugs(store, f"plan {q}")) == n, q
        assert store.facets(f"plan {q}")["total"] == n, q


def test_extreme_dates_are_no_server_error(tmp_path):
    client = TestClient(create_app(tmp_path))
    for q in ("before:9999-12-31", "after:9999-12-31", "after:0001-01-01",
              "before:0001-01-01", "after:99999999d", "before:0d"):  # fmt: skip
        for path in ("/api/search", "/api/search/facets"):
            assert client.get(path, params={"q": q}).status_code == 200, (path, q)


def test_a_pages_tags_come_most_used_first(store):
    slug = page(store, "Tagged", tags=["zz", "aa", "mm"])
    page(store, "Other", tags=["zz", "mm"])
    page(store, "Third", tags=["zz"])
    assert store.page(slug)["tags"] == ["zz", "mm", "aa"]


def test_search_pages_through_hits_with_offset(tmp_path):
    client = TestClient(create_app(tmp_path))
    store = Store(tmp_path)
    made = [page(store, f"Paged {n}", "words") for n in range(7)]

    def get(**params):
        r = client.get("/api/search", params=params)
        assert r.status_code == 200
        return [h["slug"] for h in r.json()]

    for q in ("paged", "kind:note"):  # ranked, and filters alone (newest first)
        whole = get(q=q, limit=7)
        assert sorted(whole) == sorted(made)
        assert (
            get(q=q, limit=3)
            + get(q=q, limit=3, offset=3)
            + get(q=q, limit=3, offset=6)
            == whole
        ), q
        assert get(q=q, limit=3, offset=7) == []
    assert client.get("/api/search", params={"q": "x", "offset": -1}).status_code == 422
    assert client.get("/api/search", params={"q": "x", "limit": 101}).status_code == 422


def test_the_web_search_takes_image_filters(tmp_path):
    client = TestClient(create_app(tmp_path))
    store = Store(tmp_path)
    c = store.prepare({"id": new_ulid()}, ["image/png"])
    ref = store.capture(c, [("ab" * 32, "image/png", 3, "a.png")], "me")[0]
    page(store, "Words only", "no picture")
    hits = client.get("/api/search", params={"q": "has:image"}).json()
    assert [h["id"] for h in hits] == [ref["page_id"]]
    facets = client.get("/api/search/facets", params={"q": "-has:image"}).json()
    assert facets["total"] == 1
    assert facets["active"] == [
        {"token": "-has:image", "key": "has", "value": "image", "neg": True}
    ]


# ---- sort:


def test_sort_parses_and_the_last_known_one_wins():
    assert parse("garden").sort is None
    assert parse("sort:Title").sort == ("title", False)  # A to Z
    assert parse("-sort:title").sort == ("title", True)
    assert parse("sort:created").sort == ("created", True)  # newest first
    assert parse("!sort:updated").sort == ("updated", False)
    assert parse("sort:title sort:created sort:nope").sort == ("created", True)
    assert parse("sort:nope").sort is None  # ignored: the default order
    assert parse("sort:title").filters == [Filter("sort", "title", False, "sort:title")]


def test_every_sort_has_its_sql():
    assert SORT_SQL.keys() == SORTS.keys()


def test_sort_orders_search_and_filters(store):
    b = page(store, "beta fence")  # created 2026-01-01
    a = page(store, "Alpha fence", "fence fence fence")  # 01-02
    c = page(store, "gamma", "a fence", tags=["x"])  # 01-03
    edited = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    with store.connect() as conn:  # b edited last
        conn.execute("UPDATE page SET updated_at = ? WHERE slug = ?", (edited, b))
    assert slugs(store, "fence sort:title") == [a, b, c]  # case ignored
    assert slugs(store, "fence -sort:title") == [c, b, a]
    assert slugs(store, "fence sort:created") == [c, a, b]
    assert slugs(store, "fence -sort:created") == [b, a, c]
    assert slugs(store, "fence sort:updated") == [b, c, a]
    assert slugs(store, "sort:title") == [a, b, c]  # alone: every page, in that order
    assert slugs(store, "-sort:created") == [b, a, c]
    assert slugs(store, "tag:x sort:title") == [c]
    assert slugs(store, "sort:nope") == [b, c, a]  # an unknown one: newest first
    assert [h["slug"] for h in store.search("sort:title", 1, 1)] == [b]  # offset
    assert [h["slug"] for h in store.search("fence sort:title", 2, 1)] == [b, c]
    assert store.facets("sort:title")["total"] == 3
    assert store.facets("fence sort:title")["active"] == [
        {"token": "sort:title", "key": "sort", "value": "title", "neg": False}
    ]


# ---- a todo's due: and priority: (#104)


def test_due_values():
    today = date(2026, 10, 21)
    assert due("today", today) == ("=", "2026-10-21")
    assert due("<today", today) == ("<", "2026-10-21")
    assert due("<=tomorrow", today) == ("<=", "2026-10-22")
    assert due(">yesterday", today) == (">", "2026-10-20")
    assert due("2026-11-01", today) == ("=", "2026-11-01")
    assert due(">=2026-11-01", today) == (">=", "2026-11-01")
    assert due("=2026-11-01", today) == ("=", "2026-11-01")
    assert due("none", today) == ("none", None)
    for bad in ("soon", "<", "<=", "2026-02-30", "2026-1-1", "<none", "1w", "=<today"):
        assert due(bad, today) is None, bad
    assert parse("due:<Today").filters == [Filter("due", "<today", False, "due:<Today")]


def todo(store, title, due=None, priority=None, **fields):
    slug = page(store, title, kind="todo", **fields)
    store.update_page(
        slug, None, None, None, "me", todo={"due": due, "priority": priority}
    )
    return slug


def test_due_and_priority_filters(store):
    today = date.today()
    day = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    late = todo(store, "late", day(-3), "high")
    now = todo(store, "now", day(0), "low")
    soon = todo(store, "soon", day(5))
    never = todo(store, "never", priority="medium")
    note = page(store, "a note")
    noted = todo(store, "was a todo", day(-1), "high")
    store.update_page(noted, None, None, None, "me", "note")  # keeps them, unused
    assert set(slugs(store, "due:<today")) == {late}  # overdue
    assert set(slugs(store, "due:today")) == {now}
    assert set(slugs(store, "due:>today")) == {soon}
    assert set(slugs(store, "due:<=today")) == {late, now}
    assert set(slugs(store, f"due:{day(5)}")) == {soon}
    assert set(slugs(store, f"due:>={day(0)} due:<{day(5)}")) == {now}
    assert set(slugs(store, "due:none")) == {never}  # a todo's: not the note
    assert set(slugs(store, "-due:none")) == {late, now, soon, note, noted}
    assert set(slugs(store, "-due:<today")) == {now, soon, never, note, noted}
    assert slugs(store, "due:soon") == []  # not a day: nothing
    assert set(slugs(store, "priority:high")) == {late}
    assert set(slugs(store, "priority:High priority:medium")) == {late, never}  # either
    assert set(slugs(store, "priority:none")) == {soon}
    assert set(slugs(store, "-priority:high")) == {now, soon, never, note, noted}
    assert set(slugs(store, "priority:urgent")) == {late}  # Thoth's word for it
    assert slugs(store, "priority:p1") == []
    assert store.facets("due:<today")["total"] == 1
    hit = store.search("due:<today", 5)[0]
    assert (hit["due"], hit["priority"]) == (day(-3), "high")
    assert store.search("was", 5)[0]["due"] is None  # a note shows none


def test_sort_by_due_and_priority(store):
    a = todo(store, "a", "2026-11-03", "low")
    b = todo(store, "b", "2026-11-01")
    c = todo(store, "c", None, "high")
    d = todo(store, "d", "2026-11-02", "medium")
    n = page(store, "n")
    assert slugs(store, "kind:todo sort:due") == [b, d, a, c]  # soonest, none last
    assert slugs(store, "kind:todo -sort:due") == [a, d, b, c]  # none last still
    assert slugs(store, "kind:todo sort:priority") == [c, d, a, b]  # high first
    assert slugs(store, "kind:todo -sort:priority") == [a, d, c, b]
    assert slugs(store, "sort:due")[-2:] in ([c, n], [n, c])  # a note has none
