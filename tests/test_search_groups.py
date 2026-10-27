"""Search group: (#309): the server orders results by section, and media:, later: and
relative due: filter. The PWA draws the sections (web/tests/groups.test.ts)."""

from datetime import date, timedelta

import pytest

from scrap.query import Filter, parse, subtype_of
from scrap.query import due as due_of
from test_search import page, slugs, store, todo  # noqa: F401  (the fixtures)


def day(n):
    return (date.today() + timedelta(days=n)).isoformat()


def test_group_parses_and_is_not_a_search_word():
    q = parse("tag:person group:Letter group:tag")
    assert q.terms == []
    assert q.group == "tag"  # the last
    assert parse("group:none").group is None
    assert parse("group:nope").group is None
    assert parse("-group:tag").group is None
    assert parse("group:type").filters == [Filter("group", "type", False, "group:type")]


def test_relative_due_values():
    today = date(2026, 10, 21)
    assert due_of("<=7d", today) == ("<=", "2026-10-28")
    assert due_of("<1w", today) == ("<", "2026-10-28")
    assert due_of(">=2w", today) == (">=", "2026-11-04")
    assert due_of("1m", today) == ("=", "2026-11-20")
    assert due_of("d", today) == ("=", "2026-10-22")  # no number: 1
    assert due_of("100y", today) == ("=", "2126-09-27")  # 365 days each
    for bad in ("0d", "101d", "1x", "-3d", "٣d", "1000d"):
        assert due_of(bad, today) is None, bad


def test_upcoming_is_a_relative_due_search(store):  # noqa: F811
    soon, later = todo(store, "soon", day(5)), todo(store, "later", day(9))
    today_ = todo(store, "today", day(0))
    assert slugs(store, "kind:todo due:>today due:<=7d sort:due") == [soon]
    assert set(slugs(store, "due:<=7d")) == {soon, today_}
    assert slugs(store, "due:>=2w") == []
    assert later


def test_subtype_follows_the_medium():
    assert [subtype_of(m) for m in ("book", "tv", "podcast", "game")] == [
        "read", "watch", "listen", "play",
    ]  # fmt: skip
    assert subtype_of(None) == subtype_of("pigeon") == "read"


def test_media_and_later_filters(store):  # noqa: F811
    book = page(store, "Dune", kind="consume", media_type="book", subtype="read")
    film = page(store, "Alien", kind="consume", media_type="film", subtype="watch")
    show = page(store, "Lie to me", kind="consume", media_type="tv", subtype="watch")
    bare = page(store, "Old link", kind="consume")  # captured before types
    note = page(store, "Note", media_type="book")
    assert set(slugs(store, "media:book")) == {book, note}
    assert slugs(store, "kind:later media:Book") == [book]
    assert set(slugs(store, "media:film media:tv")) == {film, show}  # either
    assert set(slugs(store, "later:watch")) == {film, show}
    assert set(slugs(store, "later:read")) == {book, bare}  # unset: read
    assert slugs(store, "later:read tag:nothing") == []
    assert slugs(store, "media:pigeon") == [] == slugs(store, "later:eat")
    assert set(slugs(store, "kind:later -later:watch")) == {book, bare}
    assert set(slugs(store, "kind:later -media:tv")) == {book, film, bare}


def test_group_letter_orders_a_to_z_across_pages(store):  # noqa: F811
    titles = ["beta", "Écu", "alpha", "9 lives", "Eagle", "Zed"]
    made = {t: page(store, t) for t in titles}
    got = slugs(store, "group:letter")
    assert got == [made[t] for t in ("alpha", "beta", "Eagle", "Écu", "Zed", "9 lives")]
    # a page of the API continues where the one before stopped
    assert [h["slug"] for h in store.search("group:letter", 2, 2)] == got[2:4]


def test_group_tag_sections_with_other_last(store):  # noqa: F811
    p_zed = page(store, "p1", tags=["person/zed"])
    p_family = page(store, "p2", tags=["person/family/gran", "person/zed"])
    p_friend = page(store, "p3", tags=["person/friend"])
    p_none = page(store, "p4", tags=["person"])
    p_ab = page(store, "p5", tags=["person/family"])
    other = page(store, "p6", tags=["place"])
    got = slugs(store, "tag:person group:tag sort:title")
    assert got == [p_family, p_ab, p_friend, p_zed, p_none]
    assert other not in got
    # no tag filter: not grouped by tag
    assert slugs(store, "group:tag sort:title") == slugs(store, "sort:title")
    hits = {h["slug"]: h for h in store.search("tag:person", 20)}
    assert sorted(hits[p_family]["tags"]) == ["person/family/gran", "person/zed"]


def test_group_type_puts_done_last(store):  # noqa: F811
    play = page(store, "Chess", kind="consume", subtype="play")
    read = page(store, "Dune", kind="consume")
    watch = page(store, "Alien", kind="consume", subtype="watch", status="in_progress")
    done = page(store, "Old", kind="consume", subtype="read", status="done")
    listen = page(store, "Pod", kind="consume", subtype="listen")
    assert slugs(store, "kind:later group:type sort:title") == [
        read, watch, listen, play, done,
    ]  # fmt: skip


def test_group_now_and_due_follow_the_todos_screen(store):  # noqa: F811
    od2, od1 = todo(store, "od2", day(-5)), todo(store, "od1", day(-2), "high")
    today_ = todo(store, "today", day(0))
    high = todo(store, "high", priority="high")
    open_hi = todo(store, "open hi", day(3), "high")
    open_med = todo(store, "open med", day(2), "medium")
    open_lo = todo(store, "open lo", day(8), "low")
    open_none = todo(store, "open none")
    asleep = todo(store, "asleep", day(1))
    store.update_page(asleep, None, None, None, "me", todo={"snoozed_until": day(4)})
    done = todo(store, "done", day(-1), status="done")
    got = slugs(store, "kind:todo group:now")
    # Overdue (oldest due first), Today, High priority (dated or not, soonest due
    # first: a dated high above an undated one), Open (by priority, then due), Snoozed,
    # Done
    assert got == [
        od2, od1, today_, open_hi, high, open_med, open_lo, open_none, asleep, done,
    ]  # fmt: skip
    # an order chosen is kept inside the sections
    assert slugs(store, "kind:todo group:now sort:title")[:2] == [od1, od2]
    by_due = slugs(store, "kind:todo group:due")  # (no date: as found)
    assert by_due[:7] == [od2, od1, today_, asleep, open_med, open_hi, open_lo]
    assert set(by_due[7:9]) == {high, open_none}
    assert by_due[9] == done


def test_the_api_groups_past_the_first_page(tmp_path):
    from fastapi.testclient import TestClient

    from scrap.app import create_app

    s = __import__("scrap.store", fromlist=["Store"]).Store(tmp_path)
    s.migrate()
    for i in range(30):
        page(s, f"{'b' if i % 2 else 'a'}{i:02d}", tags=["person/x"])
    client = TestClient(create_app(tmp_path))
    first = client.get("/api/search", params={"q": "group:letter", "limit": 15}).json()
    rest = client.get(
        "/api/search", params={"q": "group:letter", "limit": 15, "offset": 15}
    ).json()
    letters = [h["title"][0] for h in first + rest]
    assert letters == sorted(letters)
    assert first[0]["tags"] == ["person/x"]


@pytest.mark.parametrize("bad", ["group:", "group:none"])
def test_no_group_is_the_usual_order(store, bad):  # noqa: F811
    a, b = page(store, "b"), page(store, "a")
    assert slugs(store, f"sort:title {bad}") == [b, a]
