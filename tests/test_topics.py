# pyright: reportOptionalSubscript=false
"""Claude's topic pages (#261): storage and the migration, discovery and the weekly
pass (Claude faked), the synthesis, freshness, search, Related, the API, MCP and the
CLI."""

import json
import re
import time
from contextlib import closing
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client

from scrap import claude, enrich, ingest, mcp_server
from scrap.app import create_app
from scrap.store import (
    Store,
    connect,
    model_summary,
    new_ulid,
    now,
    topics,
    writeups,
)

SYNTHESIS = {
    "summary": "ibek builds EPICS IOCs from YAML.",
    "text": "## Overview\n\nibek makes IOCs.\n\n## Key facts\n\n- It reads YAML [[1]]"
    " [[2|the schema]].\n- Unknown [[9]].",
}


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH_DEBOUNCE", "0")


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    return store


def note(store, text, tags=None):
    c = store.prepare({"id": new_ulid(), "text": text}, [])
    return store.capture(c, [], "me", tags)[0]


def numbered(messages, title: str) -> int:
    """A page's number in a discovery call's index, by its title."""
    text = messages[0]["content"][0]["text"]
    index = text.split("<index>")[1].split("</index>")[0]
    for line in index.splitlines():
        n, _, rest = line.partition(". ")
        if rest.split(" | ")[0] == title:
            return int(n)
    raise AssertionError(f"{title} is not in the index")


class Fake:
    """claude.complete, faked: the answer by the call's schema; discovery's is a
    function of the user turn (to find pages' numbers); each call recorded."""

    def __init__(self, discovery: Any = None, synthesis: Any = SYNTHESIS):
        self.discovery = discovery or (lambda messages: {"new": [], "add": []})
        self.synthesis = synthesis
        self.calls: list[dict[str, Any]] = []

    def __call__(self, model, system, messages, schema, blob, **kw):
        kind = (
            "discovery" if schema is enrich.DISCOVERY_SCHEMA
            else "topic" if schema is enrich.TOPIC_SCHEMA
            else "related" if schema is enrich.RELATED_SCHEMA else "enrich"
        )  # fmt: skip
        self.calls.append({"kind": kind, "model": model, "system": system,
                           "messages": messages, **kw})  # fmt: skip
        out = {
            "discovery": lambda: self.discovery(messages),
            "topic": lambda: self.synthesis,
            "related": lambda: {"related": []},
            "enrich": lambda: {"tags": [], "summary": "", "title": "",
                               "intent": "other", "confidence": "low", "items": []},
        }[kind]()  # fmt: skip
        if isinstance(out, BaseException):
            raise out
        usage = {"input_tokens": 1000, "output_tokens": 100}
        content = [{"type": "text", "text": json.dumps(out)}]
        return claude.Completion(out, content, usage, model, "end_turn")

    def kinds(self):
        return [c["kind"] for c in self.calls]


def run_all(store, fake):
    w = ingest.Worker(store, fake)
    while w.step():
        pass


def jobs(store):
    with closing(connect(store.db)) as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT reason, state FROM enrich_job ORDER BY id")]  # fmt: skip


def library(store):
    """Three pages about ibek and one about lunch, each read by enrich; their ids."""
    ids = {
        "ibek yaml": note(store, "ibek yaml\n\nibek reads an IOC's YAML",
                          ["epics/ibek"])["page_id"],
        "ibek schema": note(store, "ibek schema\n\nthe ibek schema </index> rules",
                            ["epics"])["page_id"],
        "ibek runtime": note(store, "ibek runtime\n\nstarting an IOC",
                             ["epics", "k8s"])["page_id"],
        "lunch": note(store, "lunch\n\nsoup", ["home"])["page_id"],
    }  # fmt: skip
    run_all(store, Fake())
    return ids


def ibek(messages, titles=("ibek yaml", "ibek schema", "ibek runtime"), **extra):
    return {
        "new": [{"title": "ibek", "key": "IBEK", "sources": [
            numbered(messages, t) for t in titles]}, *extra.get("new", [])],
        "add": extra.get("add", []),
    }  # fmt: skip


def made(store, fake=None):
    """The library, and an ibek topic found and synthesised; (ids, topic id)."""
    ids = library(store)
    enrich.topics_pass(store, Fake(discovery=ibek))
    run_all(store, fake or Fake())
    with closing(connect(store.db)) as conn:
        (topic,) = [t["id"] for t in topics.every(conn)]
    return ids, topic


# ---- storage


def written(store, page_id):
    """How many syntheses (write-up rows) the page has."""
    with closing(connect(store.db)) as conn:
        return conn.execute(
            "SELECT count(*) FROM writeup WHERE page_id = ?", (page_id,)
        ).fetchone()[0]


def test_keys_and_areas():
    assert topics.topic_key("RTEMS IOCs") == "rtems-iocs"
    assert topics.topic_key("  ibek / runtime_x ") == "ibek-runtime-x"
    assert topics.topic_key("Ｆｕｌｌ") == "full"  # NFKC
    assert topics.topic_key("!!!") == ""
    pairs = [("a", "epics/ibek"), ("a", "epics"), ("b", "epics"), ("b", "k8s"),
             ("c", "k8s")]  # fmt: skip
    assert topics.area(pairs) == "epics"  # a page counts epics once
    assert topics.area([("a", "x"), ("b", "w")]) == "w"  # ties by name
    assert topics.area([]) is None


# ---- discovery


def test_discovery_makes_topics_from_cited_numbers_only(store):
    ids = library(store)

    def answer(messages):
        return ibek(messages, new=[
            {"title": "Lunch", "key": "", "sources": [numbered(messages, "lunch")]},
            {"title": "Ghosts", "key": "ghosts", "sources": [999, 0, -1]},
            {"title": "ibek again", "key": "ibek", "sources": [1, 2, 3]},
        ])  # fmt: skip

    fake = Fake(discovery=answer)
    c = enrich.topics_pass(store, fake)
    assert [t["title"] for t in c["new"]] == ["ibek"]  # one source, none, a twin
    assert c["queued"] == 1 and c["stopped"] is None
    call = fake.calls[0]
    assert call["model"] == claude.model_name() and call["effort"] == claude.EFFORT
    text = call["messages"][0]["content"][0]["text"]
    assert text.count("</index>") == 1 and "&lt;/index>" not in text  # titles only
    with closing(connect(store.db)) as conn:
        (t,) = topics.every(conn)
        assert t["key"] == "ibek" and set(t["sources"]) == {
            ids["ibek yaml"],
            ids["ibek schema"],
            ids["ibek runtime"],
        }
        run = conn.execute("SELECT status, cost_microusd, request FROM topic_run"
                           ).fetchone()  # fmt: skip
        assert run[0] == "ok" and run[1] == 1000 * 4 + 100 * 20
        assert json.loads(run[2])["purpose"] == "topics"
        assert ingest.spent_today(conn, now()) >= run[1]  # in the shared budget
    page = store.page(t["id"])
    assert (page["kind"], page["kind_fixed"], page["body"]) == ("document", 1, "")
    assert page["title"] == "ibek" and page["topic"]["key"] == "ibek"
    assert [s["title"] for s in page["topic"]["sources"]] == [
        "ibek yaml", "ibek schema", "ibek runtime"]  # fmt: skip
    assert page["writeup"]["topic"] is True and page["writeup"]["state"] == "queued"
    src = store.page(ids["ibek yaml"])
    assert [x["slug"] for x in src["topics"]] == [page["slug"]]
    assert store.page(ids["lunch"])["topics"] == []
    assert jobs(store)[-1] == ("topic", "queued")


def test_existing_topics_get_sources_but_never_an_excluded_one(store):
    ids, topic = made(store)
    enrich.exclude(store, topic, ids["ibek runtime"])
    other = note(store, "ibek tutorial", ["epics"])["page_id"]
    run_all(store, Fake())

    def answer(messages):
        text = messages[0]["content"][0]["text"]
        listed = text.split("<topics>")[1].split("</topics>")[0].strip()
        runtime = numbered(messages, "ibek runtime")
        assert listed.startswith("1. ibek (ibek): sources ")
        sources, out = listed.split("sources ")[1].split("; taken out: ")
        assert str(runtime) not in sources.split() and out == str(runtime)
        return {
            "new": [],
            "add": [
                {
                    "topic": 1,
                    "sources": [
                        numbered(messages, "ibek tutorial"),
                        numbered(messages, "ibek runtime"),
                        numbered(messages, "ibek yaml"),
                    ],
                },
                {"topic": 7, "sources": [1]},
            ],
        }

    c = enrich.topics_pass(store, Fake(discovery=answer))
    # yaml is in already, and runtime was taken out: neither is reported added
    assert [[s["title"] for s in a["sources"]] for a in c["add"]] == [
        ["ibek tutorial"]]  # fmt: skip
    with closing(connect(store.db)) as conn:
        got = {s["id"]: s["excluded"] for s in topics.sources(conn, topic, True)}
    assert got[other] == 0 and got[ids["ibek runtime"]] == 1  # still excluded


def test_a_trashed_topic_is_a_veto(store):
    ids, topic = made(store)
    store.delete_page(topic)
    fake = Fake(discovery=ibek)  # proposes ibek again
    c = enrich.topics_pass(store, fake)
    text = fake.calls[0]["messages"][0]["content"][0]["text"]
    assert "Rejected topics (never make these again): ibek" in text
    assert c["new"] == [] and c["queued"] == 0
    with closing(connect(store.db)) as conn:
        assert len(topics.every(conn)) == 1
        assert topics.index(conn) == []
    assert store.page(ids["ibek yaml"])["topics"] == []
    store.delete_page(topic, undo=True)
    with closing(connect(store.db)) as conn:  # a topic is never in the index
        assert topic not in [p["id"] for p in enrich.page_index(conn)]


def test_a_dry_run_calls_but_writes_nothing(store):
    library(store)
    c = enrich.topics_pass(store, Fake(discovery=ibek), dry_run=True)
    assert [t["title"] for t in c["new"]] == ["ibek"] and c["queued"] == 0
    with closing(connect(store.db)) as conn:
        assert topics.every(conn) == []
        run = json.loads(conn.execute("SELECT request FROM topic_run").fetchone()[0])
        assert run["dry_run"] is True  # the call is paid for, and recorded
    assert jobs(store)[-1] != ("topic", "queued")


def test_the_pass_stops_at_a_pause_and_the_budget(store, monkeypatch):
    library(store)
    c = enrich.topics_pass(store, Fake(discovery=lambda m: claude.CallError(
        "outage", "busy")))  # fmt: skip
    assert c["stopped"] == "outage" and c["new"] == []
    with closing(connect(store.db)) as conn:
        assert conn.execute("SELECT status FROM topic_run").fetchone()[0] == "error"
        ingest.resume(conn, now())
    bad = enrich.topics_pass(store, Fake(discovery=lambda m: {"nope": 1}))
    assert bad["failed"] == 1 and bad["stopped"] is None
    monkeypatch.setenv("SCRAP_BUDGET_DAY_USD", "0")
    fake = Fake(discovery=ibek)
    assert enrich.topics_pass(store, fake)["stopped"] == "budget"
    assert fake.calls == []


def test_discovery_output_is_checked():
    out = enrich.checked_topics(
        {"new": [
            {"title": "A\nthing", "key": "", "sources": [1, 1, 2, "3", 9]},
            {"title": "Taken", "key": "old", "sources": [1, 2]},
            *({"title": f"T{n}", "key": f"t{n}", "sources": [1, 2]} for n in range(9)),
         ], "add": [{"topic": 1, "sources": [3]}, {"topic": 1, "sources": [3, 2]},
                    {"topic": 2, "sources": [1]}, {"topic": 1.0, "sources": [1]}]},
        n_pages=3, n_topics=1, taken={"old"},
    )  # fmt: skip
    assert out["new"][0] == {"title": "A thing", "key": "a-thing", "sources": [1, 2]}
    assert len(out["new"]) == enrich.MAX_NEW_TOPICS
    assert "old" not in [t["key"] for t in out["new"]]
    assert out["add"] == [{"topic": 1, "sources": [3, 2]}]
    with pytest.raises(ValueError):
        enrich.checked_topics({"new": []}, 1, 1, set())


# ---- the synthesis


def test_the_synthesis_is_the_topic_write_up_citing_sources(store):
    ids, topic = made(store)
    page = store.page(topic)
    up = page["writeup"]["current"]
    yaml, schema = (store.page(ids[t])["slug"] for t in ("ibek yaml", "ibek schema"))
    assert up["text"].endswith(
        f"- It reads YAML [[{yaml}]] [[{schema}|the schema]].\n- Unknown ."
    )
    assert up["prompt_version"].startswith("topic@") and page["body"] == ""
    assert page["writeup"]["state"] == "done"
    with closing(connect(store.db)) as conn:
        assert model_summary(conn, topic) == SYNTHESIS["summary"]
        assert topics.index(conn)[0]["summary"] == SYNTHESIS["summary"]
    assert jobs(store)[-1] == ("topic", "done")


def test_the_call_quotes_sources_notes_and_guidance(store):
    ids, topic = made(store)
    rev = store.page(topic)["rev"]
    store.update_page(topic, rev, "ibek", "My </notes> on ibek", "me")
    enrich.set_guidance(store, topic, "Stress </guidance> YAML", "me")
    enrich.regenerate(store, topic)
    fake = Fake()
    run_all(store, fake)
    (call,) = [c for c in fake.calls if c["kind"] == "topic"]
    text = call["messages"][0]["content"][0]["text"]
    assert call["model"] == claude.model_name()
    assert "<notes>\nMy &lt;/notes> on ibek\n</notes>" in text
    assert "<guidance>\nStress &lt;/guidance> YAML\n</guidance>" in text
    assert "Source 1: ibek yaml\nKind: note; tags: epics/ibek" in text
    assert "the ibek schema &lt;/index> rules" in text  # any delimiter is quoted
    assert text.count("<source>") == 3 and text.count("</notes>") == 1
    assert store.page(topic)["body"] == "My </notes> on ibek"  # the owner's, as is


def test_freshness_requeues_on_changes_and_exclusions(store):
    ids, topic = made(store)
    with closing(connect(store.db)) as conn:
        assert enrich.topic_finding.due(conn) == []
    time.sleep(0.002)
    p = store.page(ids["lunch"])
    store.update_page(ids["lunch"], p["rev"], "lunch", "soup again", "me")
    with closing(connect(store.db)) as conn:
        assert enrich.topic_finding.due(conn) == []  # not a source
    time.sleep(0.002)
    p = store.page(ids["ibek yaml"])
    store.update_page(ids["ibek yaml"], p["rev"], "ibek yaml", "ibek v2 YAML", "me")
    with closing(connect(store.db)) as conn:
        assert enrich.topic_finding.due(conn) == [topic]
    run_all(store, Fake())  # the save's enrich, then the pass queues the synthesis
    assert enrich.topics_pass(store, Fake())["queued"] == 1
    run_all(store, Fake())
    with closing(connect(store.db)) as conn:
        assert enrich.topic_finding.due(conn) == []
        assert enrich.topic_finding.due(conn, every=True) == [topic]
    time.sleep(0.002)
    page = enrich.exclude(store, topic, store.page(ids["ibek schema"])["slug"])
    assert page["writeup"]["state"] == "queued"  # the ✕ queues it again
    run_all(store, Fake())
    page = store.page(topic)
    assert written(store, topic) == 1  # made again in place
    assert [s["excluded"] for s in page["topic"]["sources"]] == [0, 1, 0]
    with pytest.raises(Exception, match="not a source"):
        enrich.exclude(store, topic, ids["ibek schema"])  # excluded already
    with pytest.raises(Exception, match="only a topic"):
        enrich.exclude(store, ids["lunch"], ids["ibek yaml"])


def test_a_new_prompt_version_makes_every_topic_due(store, monkeypatch):
    ids, topic = made(store)
    monkeypatch.setattr(
        enrich.topic_finding, "topic_prompt", lambda: ("p", "topic@another")
    )
    with closing(connect(store.db)) as conn:
        assert enrich.topic_finding.due(conn) == [topic]


def test_a_source_back_from_the_trash_makes_its_topic_due(store):
    ids, topic = made(store)
    time.sleep(0.002)
    store.delete_page(ids["ibek runtime"])
    assert enrich.topics_pass(store, Fake())["queued"] == 1
    run_all(store, Fake())
    with closing(connect(store.db)) as conn:
        assert enrich.topic_finding.due(conn) == []
    time.sleep(0.002)
    store.delete_page(ids["ibek runtime"], undo=True)
    with closing(connect(store.db)) as conn:
        assert enrich.topic_finding.due(conn) == [topic]


def test_a_stopped_pass_queues_no_synthesis(store, monkeypatch):
    ids, topic = made(store)
    time.sleep(0.002)
    p = store.page(ids["ibek yaml"])
    store.update_page(ids["ibek yaml"], p["rev"], "ibek yaml", "ibek v2", "me")
    run_all(store, Fake())
    before = jobs(store)
    monkeypatch.setenv("SCRAP_BUDGET_DAY_USD", "0")
    c = enrich.topics_pass(store, Fake())
    assert c["stopped"] == "budget" and c["queued"] == 0
    assert jobs(store) == before


def test_ask_on_a_topic_makes_its_synthesis_and_no_enrich_call(store):
    ids, topic = made(store)
    enrich.ask(store, topic)
    fake = Fake()
    run_all(store, fake)
    assert fake.kinds() == ["topic", "related"]
    page = store.page(topic)
    assert written(store, topic) == 1 and page["body"] == ""
    assert page["model_tags"] == [] and page["tags"] == []
    assert jobs(store)[-1] == ("ask", "done")


def test_a_topic_with_every_source_gone_is_not_synthesised(store):
    ids, topic = made(store)
    for t in ("ibek yaml", "ibek schema", "ibek runtime"):
        store.delete_page(ids[t])
    with closing(connect(store.db)) as conn:
        assert enrich.topic_finding.due(conn) == []  # none in
    assert enrich.synthesise(store, Fake(), topic) is None
    assert enrich.synthesise(store, Fake(), ids["lunch"]) is None  # not a topic


def test_a_failed_synthesis_is_retried_then_dead(store):
    library(store)
    enrich.topics_pass(store, Fake(discovery=ibek))
    fake = Fake(synthesis={"summary": "s", "text": " [[9]] "})  # empty: invalid
    run_all(store, fake)
    assert fake.kinds() == ["topic", "topic", "topic"]
    assert jobs(store)[-1] == ("topic", "dead")


# ---- search, Related, the page


def test_search_ranks_a_matching_topic_first_and_is_topic_lists_them(store):
    ids, topic = made(store)
    hits = [h["id"] for h in store.search("ibek", 10)]
    assert hits[0] == topic and set(hits[1:]) == {
        ids["ibek yaml"],
        ids["ibek schema"],
        ids["ibek runtime"],
    }
    assert [h["id"] for h in store.search("is:topic", 10)] == [topic]
    assert topic not in [h["id"] for h in store.search("-is:topic", 10)]
    # the synthesis is indexed like a write-up
    assert [h["id"] for h in store.search("makes IOCs", 10)] == [topic]


def test_an_exact_title_beats_a_topic_matching_only_beyond_its_title(store):
    ids, topic = made(store)  # the synthesis says IOCs; its title is ibek
    iocs = note(store, "IOCs\n\na list of them")["page_id"]
    hits = [h["id"] for h in store.search("iocs", 10)]
    assert hits[0] == iocs and topic in hits


def test_citations_show_in_related_both_ways(store):
    ids, topic = made(store)
    there = {r["id"]: r["via"] for r in store.page(topic)["related"]}
    assert there == {ids["ibek yaml"]: "topic", ids["ibek schema"]: "topic"}
    back = store.page(ids["ibek yaml"])["related"]
    assert [(r["id"], r["via"]) for r in back] == [(topic, "topic")]
    # a source the synthesis does not cite is in the topic, not related to it
    assert store.page(ids["ibek runtime"])["related"] == []
    assert [t["id"] for t in store.page(ids["ibek runtime"])["topics"]] == [topic]


# ---- the API, MCP and the CLI


def test_the_api_lists_topics_and_sources_and_excludes(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    store = Store(tmp_path / "data")
    ids, topic = made(store)
    (row,) = client.get("/api/topics").json()
    assert (row["id"], row["title"], row["sources"], row["area"]) == (
        topic,
        "ibek",
        3,
        "epics",
    )
    assert row["summary"] == SYNTHESIS["summary"] and row["updated_at"]
    got = client.get(f"/api/pages/{topic}/topic/sources").json()
    assert [s["title"] for s in got] == ["ibek yaml", "ibek schema", "ibek runtime"]
    assert client.get(f"/api/pages/{ids['lunch']}/topic/sources").status_code == 422
    gone = client.delete(f"/api/pages/{topic}/topic/sources/{ids['ibek runtime']}")
    assert gone.status_code == 200 and gone.json()["writeup"]["state"] == "queued"
    again = client.delete(f"/api/pages/{topic}/topic/sources/{ids['ibek runtime']}")
    assert again.status_code == 404
    got = client.get(f"/api/pages/{topic}/topic/sources").json()
    assert [s["excluded"] for s in got] == [0, 0, 1]
    assert client.get("/api/topics").json()[0]["sources"] == 2
    run_all(store, Fake())
    back = client.post(f"/api/pages/{topic}/topic/sources/{ids['ibek runtime']}")
    assert back.status_code == 200 and back.json()["writeup"]["state"] == "queued"
    assert [s["excluded"] for s in back.json()["topic"]["sources"]] == [0, 0, 0]
    again = client.post(f"/api/pages/{topic}/topic/sources/{ids['ibek runtime']}")
    assert again.status_code == 404
    assert client.get("/api/topics").json()[0]["sources"] == 3
    page = client.post(f"/api/pages/{topic}/writeup").json()  # Regenerate
    assert page["writeup"]["state"] == "queued"
    assert jobs(store)[-1] == ("topic", "queued")
    assert client.post(f"/api/pages/{ids['lunch']}/writeup").status_code == 422


def test_search_hits_say_which_are_topics(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    store = Store(tmp_path / "data")
    ids, topic = made(store)
    hits = client.get("/api/search", params={"q": "ibek"}).json()
    marks = {h["id"]: h["topic"] for h in hits}
    assert marks == {
        topic: True,
        ids["ibek yaml"]: False,
        ids["ibek schema"]: False,
        ids["ibek runtime"]: False,
    }
    assert client.get("/api/search", params={"q": "nothing-matches"}).json() == []


def test_mcp_lists_topics_and_read_shows_them(store):
    ids, topic = made(store)
    yaml = store.page(ids["ibek yaml"])["slug"]
    slug = store.page(topic)["slug"]

    async def main():
        async with Client(mcp_server.server(store)) as client:
            listed = await client.call_tool("topics", {})
            src = await client.call_tool("read", {"page": yaml})
            top = await client.call_tool("read", {"page": slug})
            return listed, src, top

    listed, src, top = (r.structured_content for r in anyio.run(main))
    (row,) = listed["results"]
    assert (row["slug"], row["sources"], row["area"]) == (slug, 3, "epics")
    assert row["url"].endswith(f"/p/{slug}")
    assert [t["slug"] for t in src["by_model"]["topics"]] == [slug]
    assert src["by_model"]["topic"] is None
    by = top["by_model"]
    assert by["writeup"]["summary"] == SYNTHESIS["summary"]
    assert by["topic"]["key"] == "ibek" and len(by["topic"]["sources"]) == 3
    assert top["content"]["body_markdown"] == ""


def test_the_cli_runs_the_topics_pass(tmp_path, capsys, monkeypatch):
    from scrap.__main__ import main

    store = Store(tmp_path)
    store.migrate()
    library(store)
    monkeypatch.setattr(claude, "complete", Fake(discovery=ibek))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    main(["enrich", "--topics", "--dry-run", "--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert re.search(r"would make topic 'ibek' \(ibek\) from: ibek yaml; ", out)
    assert "would queue 0 syntheses" in out
    main(["enrich", "--topics", "--limit", "0", "--data-dir", str(tmp_path)])
    assert "1 new, 0 with new sources; queued 0 syntheses" in capsys.readouterr().out
    main(["enrich", "--topics", "--data-dir", str(tmp_path)])
    assert "queued 1 syntheses" in capsys.readouterr().out
    monkeypatch.setenv("SCRAP_INGEST", "off")
    main(["enrich", "--topics", "--data-dir", str(tmp_path)])
    assert "topics: Claude enrichment is off" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["enrich", "--topics", "--related", "--data-dir", str(tmp_path)])


def test_older_schema_reads_no_write_up_as_a_topic(store):
    """writeups.shown on a page that is not a board nor a topic stays None."""
    page_id = note(store, "x")["page_id"]
    with closing(connect(store.db)) as conn:
        writeups.put(conn, page_id, now(), producer="m", run_id=None,
                     prompt_version="topic@1", summary="s", text="t",
                     guidance=None)  # fmt: skip
        assert writeups.shown(conn, page_id) is None


def test_the_mcp_writeup_tool_refuses_a_topic_without_an_image(store):
    _, topic = made(store)

    async def main():
        async with Client(mcp_server.server(store)) as client:
            return await client.call_tool("writeup", {"page": topic, "guidance": "x"})

    out = anyio.run(main)
    assert out.is_error and "no image" in str(out.content)
    with closing(connect(store.db)) as conn:  # nothing queued, no guidance kept
        assert conn.execute("SELECT count(*) FROM writeup_guidance").fetchone()[0] == 0
    assert jobs(store)[-1][0] != "writeup"
