# pyright: reportOptionalSubscript=false
"""Enrich (#85): text pages tagged, summarised and linked by Claude (faked)."""

import json
from contextlib import closing
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scrap import claude, enrich, fetch
from scrap.app import create_app
from scrap.ingest import Worker, spent_today
from scrap.store import Store, connect, new_ulid

LONG = "Plans for the garden shed.\n\n" + "We will build it from larch. " * 12


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH_DEBOUNCE", "0")


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    return store


def capture(store, text=None, url=None, kind=None, tags=None):
    data: dict[str, Any] = {"id": new_ulid(), "text": text, "url": url}
    if kind:
        data["kind"] = kind
    c = store.prepare(data, [])
    return store.capture(c, [], "me", tags)[0]


class Fake:
    """claude.complete, faked: answers with out (a function of the request, or a
    dict) and records each call."""

    def __init__(self, out: Any = None, error=None, usage=None):
        self.out, self.error, self.calls = out, error, []
        self.usage = usage or {"input_tokens": 1000, "output_tokens": 100}

    def __call__(self, model, system, messages, schema, blob, **kw):
        self.calls.append({"model": model, "system": system, "messages": messages,
                           "schema": schema, **kw})  # fmt: skip
        if self.error:
            raise self.error
        out: Any = (
            self.out(system, messages) if callable(self.out) else self.out
        ) or answer()
        return claude.Completion(
            output=out,
            content=[{"type": "text", "text": json.dumps(out)}],
            usage=self.usage,
            served_model="claude-haiku-5-5",
            stop_reason="end_turn",
        )


def answer(tags=(), summary="", title="", related=()):
    return {"tags": list(tags), "summary": summary, "title": title,
            "related": list(related)}  # fmt: skip


def worker(store, fake, fetcher=None):
    w = Worker(store, fake, fetcher)
    return w


def run_all(w):
    n = 0
    while w.step():
        n += 1
    return n


def jobs(store):
    with closing(connect(store.db)) as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT reason, state, failures FROM enrich_job ORDER BY id")]  # fmt: skip


# Triggers


def test_a_note_or_link_capture_queues_enrich_a_photo_does_not(store):
    capture(store, "a note")
    capture(store, url="https://example.com/a")
    assert jobs(store) == [("capture", "queued", 0), ("capture", "queued", 0)]


def test_nothing_is_queued_with_ingest_off(store, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "off")
    capture(store, "a note")
    assert jobs(store) == []
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH", "off")
    capture(store, "another")
    assert jobs(store) == []


def test_a_note_waits_for_the_debounce_a_link_does_not(store, monkeypatch):
    monkeypatch.setenv("SCRAP_ENRICH_DEBOUNCE", "3600")
    capture(store, "a note")
    capture(store, url="https://example.com/a")
    fake = Fake(answer())
    w = worker(store, fake, lambda url: fetch.Fetched(url, "A", "", "text"))
    assert run_all(w) == 1  # the link only
    assert [r[1] for r in jobs(store)] == ["queued", "done"]


def test_saves_move_one_queued_job_and_ask_runs_it_now(store, monkeypatch):
    ref = capture(store, "a note")
    monkeypatch.setenv("SCRAP_ENRICH_DEBOUNCE", "3600")
    store.update_page(ref["page_id"], 1, None, "a note, edited", "me")
    store.update_page(ref["page_id"], 2, None, "a note, edited again", "me")
    assert jobs(store) == [("save", "queued", 0)]  # one job, moved
    assert run_all(worker(store, Fake(answer()))) == 0  # not due
    enrich.ask(store, ref["page_id"])
    assert jobs(store) == [("ask", "queued", 0)]
    assert run_all(worker(store, Fake(answer()))) == 1


def test_a_tag_edit_alone_queues_nothing(store, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "off")
    ref = capture(store, "a note")
    monkeypatch.setenv("SCRAP_INGEST", "on")
    store.update_page(ref["page_id"], None, None, None, "me", tags=["x"])
    assert jobs(store) == []


# The call and what it adds


def pick(title):
    """A fake's answer for a related call: the index number of the page titled so."""

    def out(system, messages):
        if "## Other pages" not in system:
            return answer(["diy", "garden", "Home"], "A larch shed, planned.", "x")
        index = system.split("## Other pages")[1]
        n = [int(x.split(".")[0]) for x in index.splitlines() if title in x]
        return answer(related=n)

    return out


def test_tags_and_summary_are_added_apart_from_the_text_not_related(store):
    capture(store, "Larch prices at the timber yard", tags=["diy"])
    ref = capture(store, LONG, tags=["home"])
    fake = Fake(pick("Larch prices"))
    run_all(worker(store, fake))
    page = store.page(ref["page_id"])
    assert page["body"] == LONG.strip()  # never edited
    assert page["title"] == "Plans for the garden shed."  # a note keeps its title
    assert sorted(page["tags"]) == ["diy", "garden", "home"]
    assert sorted(page["model_tags"]) == ["diy", "garden"]  # home was the user's
    assert page["enrich"]["summary"] == "A larch shed, planned."
    assert page["enrich"]["state"] == "done"
    assert page["related"] == []  # the nightly pass, or Ask, does that
    # the call: no tools, the small model, the vocabulary with counts, no index
    call = fake.calls[0]
    assert call["model"] == claude.TEXT_MODEL and call["effort"] == "low"
    assert "diy (1)" in call["system"] and "home (1)" in call["system"]
    assert all("## Other pages" not in c["system"] for c in fake.calls)
    # the summary is searchable
    hits = store.search("planned", 10)
    assert [h["id"] for h in hits] == [ref["page_id"]]


def test_ask_also_picks_related_pages_shown_both_ways(store):
    other = capture(store, "Larch prices at the timber yard", tags=["diy"])
    ref = capture(store, LONG, tags=["diy"])
    run_all(worker(store, Fake(pick("Larch prices"))))
    enrich.ask(store, ref["page_id"])
    fake = Fake(pick("Larch prices"))
    run_all(worker(store, fake))
    assert len(fake.calls) == 2  # tags and summary, then related
    assert [r["id"] for r in store.page(ref["page_id"])["related"]] == [
        other["page_id"]
    ]
    back = store.page(other["page_id"])["related"]  # the older page learns of it
    assert [(r["id"], r["via"]) for r in back] == [(ref["page_id"], "claude")]
    assert jobs(store)[-1] == ("ask", "done", 0)


def test_a_failed_related_call_on_ask_charges_the_job(store):
    ref = capture(store, "a note")
    run_all(worker(store, Fake(answer())))
    enrich.ask(store, ref["page_id"])

    def out(system, messages):
        return {"nope": 1} if "## Other pages" in system else answer()

    run_all(worker(store, Fake(out)))
    # invalid output is retried at once, and the third failure kills the job
    assert jobs(store)[-1][1:] == ("dead", 3)


def test_a_short_note_is_tagged_but_not_summarised(store):
    ref = capture(store, "buy milk")
    fake = Fake(answer(["shopping"], "Milk."))
    run_all(worker(store, fake))
    page = store.page(ref["page_id"])
    assert page["tags"] == ["shopping"]
    assert page["enrich"]["summary"] is None
    text = fake.calls[0]["messages"][0]["content"][0]["text"]
    assert "No summary is wanted." in text


def test_invented_tags_are_capped(store, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "off")
    capture(store, "first", tags=["known"])
    monkeypatch.setenv("SCRAP_INGEST", "on")
    ref = capture(store, "second")
    tags = ["new1", "known", "new2", "new3", "#New1"]
    run_all(worker(store, Fake(answer(tags))))
    page = store.page(ref["page_id"])
    assert sorted(page["tags"]) == ["known", "new1", "new2"]


# The nightly related pass


def test_the_related_pass_does_changed_pages_only(store, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "off")
    a = capture(store, "Larch prices at the timber yard", tags=["diy"])
    b = capture(store, "Shed plans in larch", tags=["diy"])
    fake = Fake(pick("Larch prices"))
    assert enrich.related_pass(store, fake, dry_run=True)["pages"] == 2
    counts = enrich.related_pass(store, fake)
    assert counts == {"pages": 2, "done": 2, "failed": 0, "stopped": None}
    assert [r["id"] for r in store.page(b["page_id"])["related"]] == [a["page_id"]]
    # nothing changed: nothing to do; an edit makes that page stale again
    assert enrich.related_pass(store, fake)["pages"] == 0
    store.update_page(b["page_id"], 1, None, "Shed plans in larch, v2", "me")
    assert enrich.related_pass(store, fake, dry_run=True)["pages"] == 1
    assert enrich.related_pass(store, fake, every=True, dry_run=True)["pages"] == 2


def test_the_related_pass_stops_at_a_pause_and_the_budget(store, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "off")
    for n in range(3):
        capture(store, f"page {n}")
    out = enrich.related_pass(store, Fake(error=claude.CallError("outage", "529")))
    assert out["stopped"] == "outage" and out["done"] == 0
    assert enrich.related_pass(store, Fake(answer()))["stopped"] == "outage"  # paused
    with closing(connect(store.db)) as conn:
        conn.execute("UPDATE queue_state SET paused_until = NULL, reason = NULL")
    monkeypatch.setenv("SCRAP_BUDGET_DAY_USD", "0.0001")
    big = Fake(answer(), usage={"input_tokens": 10_000, "output_tokens": 0})
    out = enrich.related_pass(store, big)
    assert out == {"pages": 3, "done": 1, "failed": 0, "stopped": "budget"}
    # a content error is counted and the next page tried
    with closing(connect(store.db)) as conn:
        conn.execute("UPDATE queue_state SET paused_until = NULL, reason = NULL")
    monkeypatch.setenv("SCRAP_BUDGET_DAY_USD", "3")
    out = enrich.related_pass(store, Fake(error=claude.CallError("content", "400")))
    assert out["failed"] == 2 and out["stopped"] is None


def test_candidates_find_pages_by_tags_and_words_within_the_cap(store, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "off")
    monkeypatch.setattr(enrich, "BY_TAGS", 2)
    me = capture(store, "Larch cladding for the shed", tags=["shed"])
    tagged = [capture(store, f"tagged {n}", tags=["shed"]) for n in range(3)]
    worded = capture(store, "Where to buy larch boards")
    for n in range(20):
        capture(store, f"filler {n}")
    with closing(connect(store.db)) as conn:
        found = [c["id"] for c in enrich.candidates(conn, me["page_id"], limit=6)]
    assert len(found) == 6 and me["page_id"] not in found
    assert set(found[:2]) <= {t["page_id"] for t in tagged}  # BY_TAGS of them
    assert worded["page_id"] in found[2:4]  # then the words


def test_the_user_wins_on_tags(store):
    ref = capture(store, "a note about sheds", tags=["mine"])
    run_all(worker(store, Fake(answer(["shed", "wood"]))))
    page = store.page(ref["page_id"])
    assert sorted(page["tags"]) == ["mine", "shed", "wood"]
    # the user takes one of Claude's off, and keeps the other
    store.update_page(ref["page_id"], None, None, None, "me", tags=["mine", "wood"])
    enrich.ask(store, ref["page_id"])
    run_all(worker(store, Fake(answer(["shed", "wood", "timber"]))))
    page = store.page(ref["page_id"])
    assert sorted(page["tags"]) == ["mine", "timber", "wood"]  # shed stays off
    # putting it back by hand makes it the user's
    store.update_page(ref["page_id"], None, None, None, "me", tags=["mine", "shed"])
    assert store.page(ref["page_id"])["model_tags"] == []


def test_a_stale_tag_editor_keeps_a_tag_claude_added_meanwhile(store):
    ref = capture(store, "a note about sheds", tags=["mine"])
    shown = store.page(ref["page_id"])["tags"]  # the editor opens: ["mine"]
    run_all(worker(store, Fake(answer(["shed"]))))  # Claude adds shed meanwhile
    store.update_page(ref["page_id"], None, None, None, "me", tags=["mine", "wood"],
                      tags_shown=shown)  # fmt: skip
    page = store.page(ref["page_id"])
    assert page["tags"] == ["mine", "shed", "wood"] and page["model_tags"] == ["shed"]
    # an editor that showed shed and saved without it takes it off for good
    shown = page["tags"]
    store.update_page(ref["page_id"], None, None, None, "me", tags=["mine", "wood"],
                      tags_shown=shown)  # fmt: skip
    enrich.ask(store, ref["page_id"])
    run_all(worker(store, Fake(answer(["shed"]))))
    page = store.page(ref["page_id"])
    assert page["tags"] == ["mine", "wood"] and page["model_tags"] == []


def test_a_full_page_keeps_claude_tags_it_has_no_room_for_on(store):
    ref = capture(store, "a note about sheds")
    run_all(worker(store, Fake(answer(["shed"]))))  # added while the editor was open
    full = [f"t{i}" for i in range(64)]
    store.update_page(ref["page_id"], None, None, None, "me", tags=full,
                      tags_shown=[])  # fmt: skip
    page = store.page(ref["page_id"])
    assert len(page["tags"]) == 64 and "shed" not in page["tags"]
    with closing(connect(store.db)) as conn:  # no room, but not taken off: still on
        assert [tuple(r) for r in conn.execute("SELECT tag, state FROM model_tag")] == [
            ("shed", "on")
        ]


def test_the_api_takes_the_tags_the_editor_was_shown(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    data = {"id": new_ulid(), "text": "a note about sheds"}
    page_id = client.post("/api/captures", json=data).json()["page_id"]
    store = Store(tmp_path / "data")
    run_all(worker(store, Fake(answer(["shed"]))))  # Claude adds shed meanwhile
    url = f"/api/pages/{page_id}"
    kept = client.patch(url, json={"tags": ["wood"], "tags_shown": []}).json()
    assert kept["tags"] == ["shed", "wood"] and kept["model_tags"] == ["shed"]
    taken = client.patch(url, json={"tags": ["wood"], "tags_shown": kept["tags"]})
    assert taken.json()["tags"] == ["wood"] and taken.json()["model_tags"] == []
    many = {"tags": [], "tags_shown": [f"t{i}" for i in range(65)]}
    assert client.patch(url, json=many).status_code == 422


def test_a_save_reads_again_but_adds_no_tags(store):
    ref = capture(store, "a note")
    run_all(worker(store, Fake(answer(["one"]))))
    store.update_page(ref["page_id"], 1, None, LONG, "me")
    run_all(worker(store, Fake(answer(["two"], "Now about a shed."))))
    page = store.page(ref["page_id"])
    assert page["tags"] == ["one"]
    assert page["enrich"]["summary"] == "Now about a shed."


def test_a_trashed_page_is_skipped(store):
    ref = capture(store, "a note")
    store.delete_page(ref["page_id"])
    fake = Fake(answer(["x"]))
    run_all(worker(store, fake))
    assert fake.calls == []


# Links


def page_fetch(url):
    return fetch.Fetched(
        url + "?final", "The Shed Book | Example", "All about sheds", "Sheds. " * 50
    )


def test_a_link_is_fetched_titled_summarised_and_filed_as_later(store):
    url = "https://example.com/shed"
    ref = capture(store, url=url)
    assert store.page(ref["page_id"])["title"] == url
    fake = Fake(answer(["sheds"], "A book on sheds.", "The Shed Book"))
    run_all(worker(store, fake, page_fetch))
    page = store.page(ref["page_id"])
    assert page["title"] == "The Shed Book"
    assert page["kind"] == "consume"
    assert page["fields"] == {"subtype": "read", "status": "open", "source": url}
    assert page["body"] == url
    assert page["enrich"]["summary"] == "A book on sheds."
    assert page["enrich"]["source"] == url + "?final"
    sent = fake.calls[0]["messages"][0]["content"][0]["text"]
    assert "Sheds. Sheds." in sent and "<fetched>" in sent
    # the stored request keeps the link and a placeholder, not the article
    with closing(connect(store.db)) as conn:
        row = conn.execute("SELECT request FROM enrich_run").fetchone()
    request = json.loads(row[0])
    stored = request["messages"][0]["content"][0]["text"]
    assert "Sheds. Sheds." not in stored and "[fetched text:" in stored


def test_a_link_keeps_a_kind_the_user_chose_and_a_title_they_typed(store):
    url = "https://example.com/shed"
    fixed = capture(store, url=url, kind="note")  # chosen: kind_fixed
    shared = capture(store, f"My own title\n{url}")  # a share with its title
    run_all(worker(store, Fake(answer(title="Theirs")), page_fetch))
    assert store.page(fixed["page_id"])["kind"] == "note"
    assert store.page(shared["page_id"])["title"] == "My own title"


def test_a_failed_fetch_still_tags_the_link(store):
    def refuse(url):
        raise fetch.FetchError("the address is private or local: not fetched")

    ref = capture(store, url="http://10.0.0.1/admin")
    fake = Fake(answer(["network"]))
    run_all(worker(store, fake, refuse))
    sent = fake.calls[0]["messages"][0]["content"][0]["text"]
    assert "could not be fetched: the address is private" in sent
    assert store.page(ref["page_id"])["tags"] == ["network"]


# Failures, pauses and spend


def test_an_outage_pauses_the_queue_and_refunds_the_job(store):
    capture(store, "a note")
    w = worker(store, Fake(error=claude.CallError("outage", "529")))
    assert w.step() is True
    assert jobs(store) == [("capture", "queued", 0)]
    with closing(connect(store.db)) as conn:
        assert conn.execute("SELECT reason FROM queue_state").fetchone()[0] == "outage"
    assert w.step() is False  # paused


def test_a_content_error_is_charged_and_the_third_kills_the_job(store):
    capture(store, "a note")
    w = worker(store, Fake(error=claude.CallError("content", "400")))
    w.step()
    assert jobs(store) == [("capture", "queued", 1)]
    with closing(connect(store.db)) as conn:
        for _ in range(2):
            conn.execute("UPDATE enrich_job SET run_after = '2000-01-01T00:00:00.000Z'")
            w.step()
    assert jobs(store) == [("capture", "dead", 3)]
    assert store.page(store.recent(1)[0]["id"])["enrich"]["state"] == "failed"


def test_text_runs_count_against_the_daily_budget(store, monkeypatch):
    monkeypatch.setenv("SCRAP_BUDGET_DAY_USD", "0.001")  # 1000 micro-dollars
    capture(store, "first")
    capture(store, "second")
    fake = Fake(answer(), usage={"input_tokens": 10_000, "output_tokens": 0})
    w = worker(store, fake)
    w.step()  # $0.001 on Haiku 5.5
    with closing(connect(store.db)) as conn:
        assert spent_today(conn, "2999-01-01T00:00:00.000Z") == 0
        from scrap.store import now

        assert spent_today(conn, now()) == 1000
    w.step()  # over budget: paused, not called
    assert len(fake.calls) == 1
    with closing(connect(store.db)) as conn:
        assert conn.execute("SELECT reason FROM queue_state").fetchone()[0] == "budget"


def test_a_running_job_at_start_is_charged(store):
    capture(store, "a note")
    with closing(connect(store.db)) as conn:
        conn.execute("UPDATE enrich_job SET state = 'running'")
    w = worker(store, Fake(answer()))
    with closing(connect(store.db)) as conn:
        from scrap.store import now, transaction

        with transaction(conn):
            w.enricher.recover(conn, now())
    assert jobs(store) == [("capture", "queued", 1)]


# Related, backfill, the API


def test_related_merges_claude_picks_with_backlinks(store):
    target = capture(store, "Target page")
    slug = store.page(target["page_id"])["slug"]
    linker = capture(store, f"See [[{slug}]]")
    run_all(worker(store, Fake(answer())))  # nobody picks anything
    related = store.page(target["page_id"])["related"]
    assert [(r["id"], r["via"]) for r in related] == [(linker["page_id"], "link")]


def test_backfill_queues_untagged_pages_claude_has_not_read(store, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "off")
    capture(store, "one")
    capture(store, "two", tags=["t"])
    capture(store, "three")
    assert enrich.backfill(store, dry_run=True) == 2
    assert jobs(store) == []
    assert enrich.backfill(store, limit=1) == 1
    assert jobs(store) == [("backfill", "queued", 0)]


def test_the_api_asks_claude_and_shows_its_state(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    data = {"id": new_ulid(), "text": "x"}
    page_id = client.post("/api/captures", json=data).json()["page_id"]
    page = client.post(f"/api/pages/{page_id}/enrich").json()
    assert page["enrich"]["state"] == "queued" and page["enrich"]["on"] is True
    assert page["related"] == [] and page["model_tags"] == []
    status = client.get("/api/ingest").json()
    assert status["enrich"] == {"enabled": True, "jobs": {"queued": 1}}
    assert client.post("/api/pages/NOPE/enrich").status_code == 404


def test_the_api_refuses_to_ask_claude_while_enrichment_is_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_ENRICH", "off")
    client = TestClient(create_app(tmp_path / "data"))
    data = {"id": new_ulid(), "text": "x"}
    page_id = client.post("/api/captures", json=data).json()["page_id"]
    answer = client.post(f"/api/pages/{page_id}/enrich")
    assert answer.status_code == 409 and "off" in answer.json()["detail"]
    assert client.get("/api/ingest").json()["enrich"]["jobs"] == {}


def test_the_cli_backfills_and_counts_the_related_pass(tmp_path, capsys, monkeypatch):
    from scrap.__main__ import main

    monkeypatch.setenv("SCRAP_INGEST", "off")
    store = Store(tmp_path)
    store.migrate()
    capture(store, "one")
    main(["enrich", "--backfill", "--dry-run", "--data-dir", str(tmp_path)])
    assert "would queue 1" in capsys.readouterr().out
    # off (ingest off, or no key): a note, and success, for the nightly timer
    main(["enrich", "--related", "--data-dir", str(tmp_path)])
    assert "enrichment is off" in capsys.readouterr().out
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    main(["enrich", "--related", "--data-dir", str(tmp_path)])
    assert "enrichment is off" in capsys.readouterr().out
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    main(["enrich", "--related", "--dry-run", "--data-dir", str(tmp_path)])
    assert "would pick related pages for 1 pages" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["enrich", "--data-dir", str(tmp_path)])


def test_checked_bounds_the_output():
    out = enrich.checked(
        {"tags": ["A  b", "", 7, "x" * 80], "summary": "s\x07" * 400, "title": "t"},
        set(), True, False,
    )  # fmt: skip
    assert out["tags"] == ["a b"]
    assert len(out["summary"]) <= enrich.MAX_SUMMARY
    assert out["title"] == ""  # only a link gets a title
    with pytest.raises(ValueError):
        enrich.checked({"tags": []}, set(), True, False)
    assert enrich.checked_related({"related": [True, 0, 2, 2, 3, 9]}, 3) == [2, 3]
    with pytest.raises(ValueError):
        enrich.checked_related({}, 3)
