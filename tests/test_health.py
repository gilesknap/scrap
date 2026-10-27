# pyright: reportOptionalSubscript=false
"""The store's health checks (#262): each is:/has: term in search, GET /api/health,
and outdated write-ups: only a newly read photo regenerates one, otherwise the owner
does, or scrap enrich --writeups --outdated, by is:outdated's definition (Claude
faked)."""

import io
import json
import time
from contextlib import closing
from datetime import date, timedelta
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client
from PIL import Image

from scrap import claude, enrich, ingest, mcp_server
from scrap.app import create_app
from scrap.markdown import wiki_targets
from scrap.public import origin
from scrap.store import Store, connect, fixes, health, new_ulid, now, topics, writeups

BOARD = {
    "kind": "whiteboard", "title": "Encoder pipeline", "tags": ["video"],
    "description": "A whiteboard of an encoder pipeline.", "text": "Camera\nEnc",
    "elements": [], "intent": "other", "confidence": "low", "items": [],
}  # fmt: skip
WRITEUP = {"summary": "An encoder pipeline.", "text": "## Overview\n\nThe camera."}
SYNTHESIS = {"summary": "About ibek.", "text": "## Overview\n\nibek [[1]]."}


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH_DEBOUNCE", "0")
    monkeypatch.delenv("SCRAP_NOTIFY_URL", raising=False)


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    store.prompts = enrich.prompt_versions()
    return store


class Fake:
    """claude.complete, faked: the answer by the call's schema; each call's kind
    recorded, in order."""

    def __init__(self, writeup: Any = WRITEUP, discovery: Any = None):
        self.writeup, self.discovery = writeup, discovery
        self.calls: list[str] = []

    def __call__(self, model, system, messages, schema, blob, **kw):
        kind = (
            "photo" if schema is claude.SCHEMA
            else "writeup" if schema is enrich.WRITEUP_SCHEMA
            else "topic" if schema is enrich.TOPIC_SCHEMA
            else "discovery" if schema is enrich.DISCOVERY_SCHEMA
            else "related" if schema is enrich.RELATED_SCHEMA else "enrich"
        )  # fmt: skip
        self.calls.append(kind)
        out = {
            "photo": lambda: BOARD,
            "writeup": lambda: self.writeup,
            "topic": lambda: SYNTHESIS,
            "discovery": lambda: (
                self.discovery(messages) if self.discovery else {"new": [], "add": []}
            ),
            "related": lambda: {"related": []},
            "enrich": lambda: {"tags": [], "summary": "", "title": "",
                               "intent": "other", "confidence": "low", "items": []},
        }[kind]()  # fmt: skip
        if isinstance(out, BaseException):
            raise out
        usage = {"input_tokens": 1000, "output_tokens": 100}
        content = [{"type": "text", "text": json.dumps(out)}]
        return claude.Completion(out, content, usage, model, "end_turn")


def run_all(store, fake):
    w = ingest.Worker(store, fake)
    while w.step():
        pass


def jpeg(colour="red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 300), colour).save(out, "JPEG")
    return out.getvalue()


def note(store, text, tags=None, kind=None):
    data = {"id": new_ulid(), "text": text, **({"kind": kind} if kind else {})}
    c = store.prepare(data, [])
    return store.capture(c, [], "me", tags)[0]["page_id"]


def photo(store, colour="red", text=None):
    """A photo capture's page id (its file the same bytes for the same colour)."""
    sha, size = store.put_blob(io.BytesIO(jpeg(colour)))
    c = store.prepare({"id": new_ulid(), "text": text}, ["image/jpeg"])
    return store.capture(c, [(sha, "image/jpeg", size, None)], "me")[0]["page_id"]


def sql(store, query, *args):
    with closing(connect(store.db)) as conn:
        return conn.execute(query, args).fetchall()


def found(store, query):
    return {h["id"] for h in store.search(query, 100)}


def edit(store, page_id, body):
    page = store.page(page_id)
    store.update_page(page_id, page["rev"], None, body, "me")


def tick():
    """A moment, so what follows is later than what went before (ms timestamps)."""
    time.sleep(0.002)


def older(store, table, column, page_id, days=1):
    """A page's rows in table, their column days older (later is newer)."""
    sql(store, f"UPDATE {table} SET {column} = strftime('%Y-%m-%dT%H:%M:%fZ',"
        f" {column}, ?) WHERE page_id = ?", f"-{days} days", page_id)  # fmt: skip


# ---- the checks


def test_wiki_targets_are_page_links_outside_code():
    text = (
        "[[a]] and [[ b | B ]] and [[a]] again, ![[img.png]] an embed,\n"
        "`[[in-code]]` and\n\n```\n[[ -n x ]]\n```\n"
    )
    assert wiki_targets(text) == ["a", "b"]
    assert wiki_targets("no links") == []


HERE = "https://scrap.example.ts.net:8446"
LAN = "http://192.168.1.10:8000"


def test_wiki_targets_count_a_page_s_address_on_any_public_origin():
    """#290: a Markdown link or autolink to /p/<slug>, as a path or on one of the
    origins given, is a page link; another site's, an image or one in code is not."""
    text = (
        f"[A]({HERE}/p/a?x=1#h) and [B](HTTP://192.168.1.10:8000/p/b) and <{HERE}/p/c>"
        " and [D](/p/d) and [[e]]\n\n[No](https://elsewhere.org/p/x) and"
        f" ![img]({HERE}/p/img) and `[c]({HERE}/p/code)` and [up]({HERE}/p/Up)"
        f" and [deep]({HERE}/p/a/b) and [{HERE}/api/blobs/x]({HERE}/api/blobs/x)"
    )
    assert wiki_targets(text, (HERE, LAN)) == ["a", "b", "c", "d", "e"]
    paths = "[q](/p/q?x=1) and [h](/p/h#h-top) and [n](/p/No#x) and [s](/p/s/)"
    assert wiki_targets(paths) == ["q", "h"]  # as the PWA opens them in place
    assert wiki_targets(text) == ["d", "e"]  # no origins: a path only
    assert wiki_targets(text, (HERE,)) == ["a", "c", "d", "e"]


def test_a_non_ascii_host_matches_its_punycode_href():
    """markdown-it writes a link's host as punycode; the origins are compared so."""
    assert origin("https://Bücher.example:443/") == "https://xn--bcher-kva.example"
    assert wiki_targets("[a](https://bücher.example/p/x)") == []  # no origins
    here = origin("https://bücher.example")
    assert here is not None
    assert wiki_targets("[a](https://bücher.example/p/x)", (here,)) == ["x"]


def test_backlinks_are_the_links_the_parser_finds(store):
    """Not one in code or an embed (![[slug]]); one in a table cell, its pipe
    escaped, is."""
    t = note(store, "Target")
    slug = store.page(t)["slug"]
    note(store, f"Code\n\n`[[{slug}]]` and\n\n```\n[[{slug}]]\n```")
    note(store, f"Embed\n\n![[{slug}]]")
    cell = note(store, f"Table\n\n| a | b |\n|---|---|\n| [[{slug}\\|label]] | x |")
    assert [b["id"] for b in store.backlinks(slug)] == [cell]


def test_a_page_s_full_address_links_it(store, monkeypatch):
    """#290: on any address in $SCRAP_PUBLIC_URL, a full-address link counts as
    [[slug]] does: backlinks, related (via link), is:orphan and has:dangling."""
    monkeypatch.setenv("SCRAP_PUBLIC_URL", f"{HERE},{LAN}")
    a = note(store, "Alpha")
    b = note(store, "Beta")
    c = note(store, "Gamma")
    slug = {"a": store.page(a)["slug"], "b": store.page(b)["slug"]}
    d = note(store, f"Delta\n\n[it]({HERE}/p/{slug['a']})")
    e = note(store, f"Epsilon\n\n<{LAN}/p/{slug['b']}> and [x]({HERE}/p/nowhere)")
    assert found(store, "is:orphan") == {c}
    assert found(store, "has:dangling") == {e}
    assert [x["id"] for x in store.backlinks(slug["a"])] == [d]
    assert [x["id"] for x in store.backlinks(slug["b"])] == [e]
    related = store.page(a)["related"]
    assert [(r["id"], r["via"]) for r in related] == [(d, "link")]
    monkeypatch.setenv("SCRAP_PUBLIC_URL", HERE)  # LAN no longer this server's
    assert found(store, "is:orphan") == {b, c, e}
    assert store.backlinks(slug["b"]) == []


def test_orphan_is_a_page_with_no_link_pick_or_topic(store):
    a = note(store, "Alpha\n\nsee [[beta]]")
    b = note(store, "Beta")
    c = note(store, "Gamma")
    d = note(store, "Delta")
    e = note(store, "Epsilon\n\na link to [[delta]]")
    assert found(store, "is:orphan") == {c}  # a links b; e links d
    store.delete_page(d)  # a link to a page in the trash links nothing
    assert found(store, "is:orphan") == {c, e}
    sql(store, "INSERT INTO related VALUES (?, ?, 0)", c, e)  # a pick, either end
    assert found(store, "is:orphan") == set()
    assert found(store, "-is:orphan") == {a, b, c, e}
    store.delete_page(c)
    assert found(store, "is:orphan") == {e}
    with closing(connect(store.db)) as conn:  # a topic and its source
        t = topics.create(conn, "Topic", "topic", "topic", "claude", now())
        assert t is not None
        topics.add_sources(conn, t, [e], "claude", now())
    assert found(store, "is:orphan") == set()


def review(store, page_id):
    """Make a page one of gc's review pages, as if gc had made it: made_by gc (its
    trigger set aside, since nothing else may change it) and its capture's source."""
    with closing(connect(store.db)) as conn:
        conn.execute("DROP TRIGGER page_made_by_fixed")
        conn.execute("UPDATE page SET made_by = 'gc' WHERE id = ?", (page_id,))
        conn.execute(fixes.MADE_BY_FIXED)
    sql(store, "UPDATE capture SET source = 'gc' WHERE page_id = ?", page_id)


def test_a_gc_review_page_is_no_orphan(store):
    a = note(store, "Alpha")
    gc_page = note(store, "Orphaned assets: October 2026", kind="todo")
    assert found(store, "is:orphan") == {a, gc_page}
    review(store, gc_page)
    assert found(store, "is:orphan") == {a}


def test_a_page_the_parser_fails_on_has_no_links_and_is_logged_once(
    store, monkeypatch, caplog
):
    from scrap.store import db

    def broken(text):
        raise RuntimeError("parser bug")

    monkeypatch.setattr(db, "wiki_targets", broken)
    monkeypatch.setattr(db, "_failed", False)
    monkeypatch.setattr(db, "_PARSED", db.OrderedDict())
    a = note(store, "Alpha\n\nsee [[nowhere]]")
    note(store, "Beta\n\nsee [[elsewhere]]")
    with caplog.at_level("ERROR", logger="scrap.store.db"):
        assert found(store, "has:dangling") == set()  # no links: not dangling
        assert a in found(store, "is:orphan")
    assert len([r for r in caplog.records if "can't parse" in r.message]) == 1


def test_the_parse_cache_drops_the_least_recently_used(monkeypatch):
    from scrap.store import db

    monkeypatch.setattr(db, "_PARSED", db.OrderedDict())
    monkeypatch.setattr(db, "_MAX_PARSED", 2)
    assert db.wiki_links("[[a]]") == '["a"]'
    db.wiki_links("[[b]]")
    db.wiki_links("[[a]]")  # used again: kept
    db.wiki_links("[[c]]")
    kept = list(db._PARSED.values())  # noqa: SLF001
    assert kept == ['["a"]', '["c"]']


def test_untagged_leaves_out_topics_and_gc_review_pages(store):
    a = note(store, "Alpha")
    note(store, "Beta", tags=["home"])
    review(store, note(store, "Orphaned assets: October 2026", kind="todo"))
    with closing(connect(store.db)) as conn:
        topics.create(conn, "Topic", "topic", "topic", "claude", now())
    assert found(store, "is:untagged") == {a}


def test_a_topic_with_sources_and_its_sources_are_not_orphans(store):
    a, b = note(store, "Alpha"), note(store, "Beta")
    with closing(connect(store.db)) as conn:
        t = topics.create(conn, "Topic", "topic", "topic", "claude", now())
        assert t is not None
    assert found(store, "is:orphan") == {a, b, t}  # no source yet
    with closing(connect(store.db)) as conn:
        topics.add_sources(conn, t, [a], "claude", now())
    assert found(store, "is:orphan") == {b}
    with closing(connect(store.db)) as conn:
        topics.exclude(conn, t, a, now())  # taken out: no longer a source in
    assert found(store, "is:orphan") == {a, b, t}


def test_stale_is_an_open_todo_unedited_for_sixty_days(store):
    old = note(store, "Fix the gate", kind="todo")
    fresh = note(store, "Fix the fence", kind="todo")
    done = note(store, "Fix the shed", kind="todo")
    snoozed = note(store, "Fix the roof", kind="todo")
    tagged = note(store, "Fix the path", kind="todo")
    a_note = note(store, "An old note")
    gc_page = note(store, "Orphaned assets: January 2026", kind="todo")
    review(store, gc_page)  # gc's review todo: its due date brings it up
    for p in (old, done, snoozed, tagged, a_note, gc_page):  # last edited in January
        sql(store, "UPDATE page SET updated_at = '2026-01-01T00:00:00.000Z',"
            " fields = json_set(fields, '$.status', ?) WHERE id = ?",
            "done" if p == done else "open", p)  # fmt: skip
    later = (date.today() + timedelta(days=3)).isoformat()
    sql(store, "UPDATE page SET snoozed_until = ? WHERE id = ?", later, snoozed)
    store.edit_meta([tagged], "me", "web", add=["garden"])  # a change of tags
    assert found(store, "is:stale") == {old}
    assert fresh not in found(store, "is:stale")
    soon = (date.today() + timedelta(days=0)).isoformat()
    sql(store, "UPDATE page SET due = ? WHERE id = ?", soon, old)  # due today
    assert found(store, "is:stale") == set()  # its due date brings it up
    sql(store, "UPDATE page SET due = '2026-01-15' WHERE id = ?", old)  # overdue
    assert found(store, "is:stale") == {old}
    sql(store, "UPDATE page SET snoozed_until = '2026-01-02' WHERE id = ?", snoozed)
    assert found(store, "is:stale") == {old, snoozed}  # its snooze is over


def test_duplicate_shares_a_file_with_another_live_page(store):
    a = photo(store, "red")
    b = photo(store, "red")  # the same bytes: one file
    c = photo(store, "blue")
    assert found(store, "is:duplicate") == {a, b}
    store.delete_page(b)  # a file shared with a page in the trash is not
    assert found(store, "is:duplicate") == set()
    store.delete_page(b, undo=True)
    review(store, b)  # one of gc's review pages
    assert found(store, "is:duplicate") == set()
    assert c not in found(store, "is:duplicate")


def test_a_deleted_embed_leaves_the_file_out_of_duplicate_and_images(store):
    """#303: the capture keeps the file (gc needs it); the page no longer shows it."""
    a = photo(store, "red")
    b = photo(store, "red")
    sha = store.page(a)["captures"][0]["blobs"][0]["sha256"]
    shown = store.page(a)["body"]
    assert found(store, "is:duplicate") == {a, b}
    tick()
    edit(store, a, "No picture now")  # the owner deletes the embed
    assert found(store, "is:duplicate") == set()
    assert a not in found(store, "has:image") and b in found(store, "has:image")
    assert a not in store.images_of([a]) and store.images_of([b])[b]["count"] == 1
    assert [r[0] for r in sql(store, "SELECT sha256 FROM capture_blob")] == [sha, sha]
    tick()
    edit(store, a, shown)  # a revert: the page shows it again
    assert found(store, "is:duplicate") == {a, b}
    assert store.images_of([a])[a]["count"] == 1


def test_a_gone_file_stays_gone_through_the_trash_and_a_new_upload(store):
    a = photo(store, "red")
    shown = store.page(a)["body"]
    tick()
    edit(store, a, "No picture")
    store.delete_page(a)
    store.delete_page(a, undo=True)  # out of the trash and back: still not shown
    assert a not in found(store, "has:image") and store.images_of([a]) == {}
    b = photo(store, "red")  # the same bytes sent again, on a new page
    c = photo(store, "red")
    assert found(store, "is:duplicate") == {b, c}
    assert store.images_of([b])[b]["count"] == 1 and a not in store.images_of([a])
    tick()
    edit(store, a, shown)
    assert found(store, "is:duplicate") == {a, b, c}


def test_a_file_never_embedded_is_kept_and_one_shown_elsewhere_stays_there(store):
    sha, size = store.put_blob(io.BytesIO(b"%PDF a document"))

    def attach(text):
        c = store.prepare({"id": new_ulid(), "text": text}, ["application/pdf"])
        files = [(sha, "application/pdf", size, "doc.pdf")]
        return store.capture(c, files, "me")[0]["page_id"]

    a, b = attach("One"), attach("Two")  # a PDF is listed below a page, never embedded
    edit(store, a, "One, edited")
    assert found(store, "is:duplicate") == {a, b}
    # a photo whose embed was deleted on one page but another page's text still shows
    p = photo(store, "green")
    q = photo(store, "green")
    tick()
    edit(store, p, "no picture")
    assert found(store, "is:duplicate") == {a, b}  # q alone holds the photo now
    assert store.images_of([q])[q]["count"] == 1 and p not in store.images_of([p])


def test_dangling_is_a_link_to_no_live_page(store):
    note(store, "Beta")
    a = note(store, "Alpha\n\n[[beta]] and [[nowhere]]")
    b = note(store, "Gamma\n\nonly [[beta|the beta page]] and `[[code]]`")
    c = note(store, "Delta\n\n[[gamma]]")
    assert found(store, "has:dangling") == {a}
    store.delete_page(b)
    assert found(store, "has:dangling") == {a, c}
    assert c not in found(store, "-has:dangling")


# ---- outdated: only write-ups are is:outdated (#291); the passes find the rest


def board(store, colour="red"):
    """A board page, read and written up; its id."""
    page_id = photo(store, colour)
    run_all(store, Fake())
    return page_id


def test_outdated_write_up_by_its_inputs_or_prompt_but_never_a_restore(store):
    page_id = board(store)
    assert found(store, "is:outdated") == set()
    tick()
    edit(store, page_id, "the board, with a note")  # its text, after the write-up
    assert found(store, "is:outdated") == {page_id}
    run_all(store, Fake())
    enrich.regenerate(store, page_id)
    run_all(store, Fake())  # a new version
    assert found(store, "is:outdated") == set()  # its related picks older: no finding
    tick()
    store.edit_meta([page_id], "me", "web", add=["video/encoders"])  # its tags
    assert found(store, "is:outdated") == {page_id}
    enrich.regenerate(store, page_id)
    run_all(store, Fake())
    store.prompts = {**store.prompts, "writeup": "writeup@another"}  # a new prompt
    assert found(store, "is:outdated") == {page_id}
    enrich.restore(store, page_id, 1, base=3)  # the owner's choice stands
    assert found(store, "is:outdated") == set()
    tick()
    edit(store, page_id, "the board, with another note")  # even for a change
    assert found(store, "is:outdated") == set()
    store.prompts = {}  # no version known: none checked
    enrich.regenerate(store, page_id)
    run_all(store, Fake())
    assert found(store, "is:outdated") == set()


# ---- a write-up linking a page with no live page is outdated (#310)


def link_writeup(store, page_id, text, restored_from=None):
    """A board's new current write-up with this text (as its cited numbers become)."""
    tick()
    (version,) = sql(store, "SELECT prompt_version FROM writeup WHERE page_id = ?"
                     " AND superseded_at IS NULL", page_id)[0]  # fmt: skip
    with closing(connect(store.db)) as conn:
        writeups.put(conn, page_id, now(), producer="claude", run_id=None,
                     prompt_version=version, summary="s", text=text, guidance=None,
                     restored_from=restored_from)  # fmt: skip


def test_a_write_up_linking_a_trashed_page_is_outdated_until_it_is_back(store):
    page_id = board(store)
    target = note(store, "Target page")
    link_writeup(
        store, page_id, f"Like [[{store.page(target)['slug']}]] and `[[nowhere]]`."
    )
    assert found(store, "is:outdated") == set()  # live link; a link in code is no link
    store.delete_page(target)
    assert found(store, "is:outdated") == {page_id}
    assert store.page(page_id)["writeup"]["outdated"] is True
    assert (
        enrich.writeup_pass(store, Fake(), outdated=True, dry_run=True)["pages"] == 1
    )  # as enrich --writeups
    store.delete_page(target, undo=True)
    assert found(store, "is:outdated") == set()
    assert store.page(page_id)["writeup"]["outdated"] is False
    store.delete_page(target)
    sql(store, "DELETE FROM page WHERE id = ?", target)  # purged: no page at all
    assert found(store, "is:outdated") == {page_id}


def test_a_restored_write_up_or_an_embed_or_a_plain_one_is_exempt(store):
    page_id = board(store)
    target = note(store, "Target page")
    slug = store.page(target)["slug"]
    store.delete_page(target)
    link_writeup(store, page_id, "No links here")
    assert found(store, "is:outdated") == set()
    link_writeup(store, page_id, f"An embed ![[{slug}]]")
    assert found(store, "is:outdated") == set()  # an embed is no link
    link_writeup(store, page_id, f"[[{slug}]]")
    assert found(store, "is:outdated") == {page_id}
    link_writeup(store, page_id, f"[[{slug}]]", restored_from=1)
    assert found(store, "is:outdated") == set()  # the owner's Restore stands


def test_a_topic_synthesis_linking_a_trashed_page_is_not_is_outdated(store):
    ids, topic = library_and_topic(store)
    store.delete_page(ids[0])
    assert found(store, "is:outdated") == set()  # the weekly pass's, not this


def test_outdated_related_pages_are_due_to_the_pass_not_is_outdated(store):
    a = note(store, "Alpha")
    b = note(store, "Beta")
    run_all(store, Fake())  # enrich, then each one's first related call
    older(store, "enrich_run", "started_at", a)
    edit(store, a, "Alpha, edited")  # its picks older than its text
    sql(store, "UPDATE enrich_run SET status = 'error' WHERE page_id = ?", b)
    with closing(connect(store.db)) as conn:  # the pass finds both
        due = {r[0] for r in conn.execute(enrich.STALE, {"all": False, "limit": -1})}
        assert due == {a, b}
        outdated = f"SELECT {health.OUTDATED_RELATED.format(p='p')} FROM page p"
        assert conn.execute(f"{outdated} WHERE p.id = ?", (a,)).fetchone()[0] == 1
    assert found(store, "is:outdated") == set()  # no finding: the nightly pass's


def library_and_topic(store):
    ids = [note(store, f"ibek {w}\n\nibek {w} text", ["epics"])
           for w in ("yaml", "schema", "runtime")]  # fmt: skip
    run_all(store, Fake())
    with closing(connect(store.db)) as conn:
        topic = topics.create(conn, "ibek", "ibek", "ibek", "claude", now())
        assert topic is not None
        topics.add_sources(conn, topic, ids, "claude", now())
    enrich.regenerate(store, topic)
    run_all(store, Fake())
    return ids, topic


def test_a_topic_due_a_synthesis_is_the_weekly_pass_s_not_is_outdated(store):
    ids, topic = library_and_topic(store)
    with closing(connect(store.db)) as conn:
        assert enrich.topic_finding.due(conn) == []
    tick()
    edit(store, ids[0], "ibek yaml, changed")
    with closing(connect(store.db)) as conn:  # the pass finds it
        assert enrich.topic_finding.due(conn) == [topic]
    assert found(store, "is:outdated") == set()  # no finding: the weekly pass's


def test_a_topic_due_by_a_new_topic_prompt_is_not_is_outdated(store, monkeypatch):
    _, topic = library_and_topic(store)
    monkeypatch.setattr(
        enrich.topic_finding, "topic_prompt", lambda: ("p", "topic@another")
    )
    with closing(connect(store.db)) as conn:  # the pass finds it, by its version
        assert enrich.topic_finding.due(conn) == [topic]
    store.prompts = {**store.prompts, "topic": "topic@another"}  # ignored even if set
    assert found(store, "is:outdated") == set()


def test_health_counts_match_the_searches_and_mcp_takes_the_terms(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    for text in ("Alpha [[nowhere]]", "Beta", "Gamma [[beta]]"):
        client.post("/api/captures", json={"id": new_ulid(), "text": text})
    got = client.get("/api/health").json()["checks"]
    assert [c["term"] for c in got] == [
        "is:orphan", "is:untagged", "is:stale", "is:duplicate", "has:dangling",
        "is:outdated",
    ]  # fmt: skip
    for c in got:
        total = client.get("/api/search/facets", params={"q": c["term"]}).json()
        assert total["total"] == c["count"], c["term"]
    assert {c["term"]: c["count"] for c in got}["has:dangling"] == 1
    store = Store(tmp_path / "data")

    async def search():
        async with Client(mcp_server.server(store)) as mcp:
            out = await mcp.call_tool("search", {"query": "is:orphan"})
            return json.loads(out.content[0].text)  # type: ignore[union-attr]

    assert [r["title"] for r in anyio.run(search)["results"]] == ["Alpha [[nowhere]]"]


def test_counts_take_one_query_each_and_no_model(store):
    with closing(connect(store.db)) as conn:
        assert [c["count"] for c in health.counts(conn, store.prompts)] == [0] * 6
    with pytest.raises(KeyError):
        health.condition("is", "nothing", {})


# ---- outdated write-ups: the owner's to make again (enrich --writeups --outdated)


def stale_board(store, colour):
    """A board page whose write-up is older than its last edit."""
    page_id = board(store, colour)
    tick()
    edit(store, page_id, f"the {colour} board, edited")
    run_all(store, Fake())  # the save's job: a board page queues none, nor a write-up
    return page_id


def test_an_edit_makes_a_write_up_outdated_not_written_again(store):
    page_id = stale_board(store, "red")
    assert store.page(page_id)["writeup"]["versions"] == 1  # only a photo read does
    assert store.page(page_id)["writeup"]["outdated"] is True
    fake = Fake()
    assert enrich.related_pass(store, fake)["done"] >= 1  # the nightly pass: related
    assert "writeup" not in fake.calls


def test_writeups_outdated_makes_only_the_outdated_ones(store):
    a = stale_board(store, "red")
    fresh = board(store, "blue")
    photo(store, "green")  # not read yet: no write-up, and not outdated
    fake = Fake()
    c = enrich.writeup_pass(store, fake, outdated=True)
    assert c == {"pages": 1, "done": 1, "failed": 0, "stopped": None}
    assert fake.calls == ["writeup"]
    assert store.page(a)["writeup"]["versions"] == 2
    assert store.page(fresh)["writeup"]["versions"] == 1
    assert store.page(a)["writeup"]["outdated"] is False
    assert enrich.writeup_pass(store, Fake(), outdated=True)["pages"] == 0


def test_writeups_outdated_keeps_to_limit_dry_run_budget_and_pause(store, monkeypatch):
    boards = [stale_board(store, c) for c in ("red", "blue", "green")]
    runs = sql(store, "SELECT count(*) FROM enrich_run")[0][0]
    fake = Fake()
    c = enrich.writeup_pass(store, fake, outdated=True, dry_run=True)
    assert c["pages"] == 3 and fake.calls == []
    assert sql(store, "SELECT count(*) FROM enrich_run")[0][0] == runs
    c = enrich.writeup_pass(store, fake, limit=2, outdated=True)
    assert c["done"] == 2 and fake.calls == ["writeup", "writeup"]
    fake = Fake(writeup=claude.CallError("outage", "busy"))
    c = enrich.writeup_pass(store, fake, outdated=True)
    assert c["stopped"] == "outage" and fake.calls == ["writeup"]
    with closing(connect(store.db)) as conn:
        ingest.resume(conn, now())
    monkeypatch.setenv("SCRAP_BUDGET_DAY_USD", "0")
    fake = Fake()
    c = enrich.writeup_pass(store, fake, outdated=True)
    assert c["stopped"] == "budget" and fake.calls == []
    assert enrich.writeup_pass(store, Fake(), outdated=True, dry_run=True)["pages"] == 1
    assert len(boards) == 3


def test_a_new_prompt_outdates_every_write_up_but_a_restored_one(store, monkeypatch):
    page_id = board(store)
    enrich.regenerate(store, page_id)
    run_all(store, Fake(writeup={"summary": "Second.", "text": "## Two"}))
    enrich.restore(store, page_id, 1, base=2)
    run_all(store, Fake())
    tick()
    edit(store, page_id, "the board, edited after the restore")
    other = board(store, "blue")
    monkeypatch.setattr(enrich.writing, "writeup_prompt", lambda pages: ("p", "w@new"))
    c = enrich.writeup_pass(store, Fake(), outdated=True)
    assert c["pages"] == 1  # the other board, for the new prompt
    assert store.page(page_id)["writeup"]["current"]["restored_from"] == 1
    assert store.page(other)["writeup"]["versions"] == 2


def test_the_page_says_its_write_up_is_outdated(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    store = Store(tmp_path / "data")
    page_id = board(store)
    view = client.get(f"/api/pages/{page_id}").json()["writeup"]
    assert view["outdated"] is False
    tick()
    edit(store, page_id, "the board, with a note")
    assert client.get(f"/api/pages/{page_id}").json()["writeup"]["outdated"] is True
    note_id = note(store, "a note")
    assert client.get(f"/api/pages/{note_id}").json()["writeup"] is None
    ids, topic = library_and_topic(store)
    assert client.get(f"/api/pages/{topic}").json()["writeup"]["outdated"] is False


def test_the_cli_makes_outdated_write_ups(store, tmp_path, capsys, monkeypatch):
    from scrap.__main__ import main

    data = str(tmp_path / "data")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    stale_board(store, "red")
    board(store, "blue")
    main(["enrich", "--writeups", "--outdated", "--dry-run", "--data-dir", data])
    assert "would write up 1 board pages" in capsys.readouterr().out
    main(["enrich", "--writeups", "--dry-run", "--data-dir", data])  # none: no change
    assert "would write up 0 board pages" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["enrich", "--related", "--outdated", "--data-dir", data])
