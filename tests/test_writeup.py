# pyright: reportOptionalSubscript=false
"""Claude's write-up of a board page (#256): storage and versions, when it is queued,
the call (Claude faked), its links, summary, search, Related, the migration, the CLI,
the API and MCP."""

import io
import json
import sqlite3
import time
from contextlib import closing
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client
from PIL import Image

from scrap import claude, enrich, ingest, mcp_server
from scrap.app import create_app
from scrap.store import (
    Store,
    connect,
    fixes,
    migrations,
    model_summary,
    new_ulid,
    now,
    writeups,
)

BOARD = {
    "kind": "whiteboard",
    "title": "Encoder pipeline",
    "tags": ["video"],
    "description": "A whiteboard of an encoder pipeline: camera, Enc and a store.",
    "text": "Camera\nEnc\nStore\nbitrate? (?)",
    "elements": [],
    "intent": "other",
    "confidence": "low",
    "items": [],
}
STICKY = {**BOARD, "kind": "whiteboard", "title": "Current actions",
          "description": "A yellow sticky note of jobs.", "text": "book MOT\npay bill",
          "intent": "list-of-actions", "confidence": "high",
          "items": [{"text": "book MOT", "done": False},
                    {"text": "pay bill", "done": False}]}  # fmt: skip
SCENE = {**BOARD, "kind": "photo", "description": "A photo of a beach."}
WRITEUP = {
    "summary": "An encoder pipeline from camera to store.",
    "text": "## Overview\n\nThe camera feeds Enc, then the store (see [[1]]).\n\n"
    "## Open questions\n\n- the bitrate (?)",
}


def jpeg(colour="red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 300), colour).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH_DEBOUNCE", "0")


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    return store


def photo(store, *colours, text=None):
    """A photo capture of one image per colour; its reference."""
    blobs = []
    for colour in colours or ("red",):
        sha, size = store.put_blob(io.BytesIO(jpeg(colour)))
        blobs.append((sha, "image/jpeg", size, None))
    c = store.prepare({"id": new_ulid(), "text": text}, ["image/jpeg"] * len(blobs))
    return store.capture(c, blobs, "me")[0]


def note(store, text, tags=None):
    c = store.prepare({"id": new_ulid(), "text": text}, [])
    return store.capture(c, [], "me", tags)[0]


class Fake:
    """claude.complete, faked: the answer by the call's schema (photo, enrich,
    related or write-up); each call is recorded."""

    def __init__(self, photo=BOARD, writeup: Any = WRITEUP, related=()):
        self.photo, self.writeup, self.related = photo, writeup, list(related)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, model, system, messages, schema, blob, **kw):
        kind = (
            "photo" if schema is claude.SCHEMA
            else "writeup" if schema is enrich.WRITEUP_SCHEMA
            else "related" if schema is enrich.RELATED_SCHEMA else "enrich"
        )  # fmt: skip
        self.calls.append({"kind": kind, "model": model, "system": system,
                           "messages": messages, "blob": blob, **kw})  # fmt: skip
        out = {
            "photo": lambda: self.photo,
            "writeup": lambda: (
                self.writeup(system) if callable(self.writeup) else self.writeup
            ),
            "related": lambda: {"related": self.related},
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


def board_page(store, fake=None, *colours):
    """A board page, read by photo ingest and written up (with everything queued)."""
    ref = photo(store, *colours)
    run_all(store, fake or Fake())
    return ref


# ---- storage and versions


def test_versions_one_current_old_kept_and_never_changed(store):
    page_id = note(store, "x")["page_id"]
    with closing(connect(store.db)) as conn:
        for n in (1, 2):
            v = writeups.put(
                conn, page_id, now(), producer="m", run_id=None,
                prompt_version="writeup@1", summary=f"s{n}", text=f"t{n}",
                guidance="g" if n == 2 else None,
            )  # fmt: skip
            assert v == n
        rows = writeups.versions(conn, page_id)
        assert [(r["version"], r["current"]) for r in rows] == [(2, True), (1, False)]
        assert rows[0]["guidance"] == "g" and rows[1]["guidance"] is None
        assert writeups.current(conn, page_id)["text"] == "t2"
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE writeup SET text = 'edited' WHERE version = 1")
        with pytest.raises(sqlite3.IntegrityError, match="stays superseded"):
            conn.execute("UPDATE writeup SET superseded_at = NULL WHERE version = 1")


def test_restore_makes_an_old_version_current_as_a_copy(store):
    ref = board_page(store)
    fake = Fake(writeup={"summary": "Second.", "text": "## Overview\n\nnewer words"})
    enrich.regenerate(store, ref["page_id"])
    run_all(store, fake)
    assert store.page(ref["page_id"])["writeup"]["current"]["version"] == 2
    with pytest.raises(enrich.StaleWriteupError):
        enrich.restore(store, ref["page_id"], 1, base=1)  # 2 is current
    with pytest.raises(Exception, match="no version 9"):
        enrich.restore(store, ref["page_id"], 9, base=2)
    page = enrich.restore(store, ref["page_id"], 1, base=2)
    up = page["writeup"]["current"]
    assert (up["version"], up["restored_from"]) == (3, 1)
    assert up["summary"] == WRITEUP["summary"] and page["writeup"]["versions"] == 3
    assert store.search("newer", 10) == []  # only the current one is searched
    assert [h["id"] for h in store.search("feeds", 10)] == [ref["page_id"]]


# ---- when it is queued


def test_a_board_is_written_up_then_its_first_related_call_sees_it(store):
    other = note(store, "Encoder settings for the camera", tags=["video"])
    run_all(store, Fake())
    ref = photo(store, "red", "blue")
    w = ingest.Worker(store, Fake())
    assert w.step() is True and jobs(store)[-1:] == [("related", "done")]  # the note's
    assert w.step() is True  # its second photo: now all read
    assert jobs(store)[-1] == ("writeup", "queued")  # no related call before it
    fake = Fake(related=[1])
    run_all(store, fake)
    assert fake.kinds() == ["writeup", "related"]
    assert jobs(store)[-2:] == [("writeup", "done"), ("related", "done")]
    related = fake.calls[1]["messages"][0]["content"][0]["text"]
    assert "<writeup>\n## Overview" in related  # the related call sees the write-up
    assert "Summary: An encoder pipeline" in related  # and its summary
    call = fake.calls[0]
    assert call["model"] == claude.model_name() and call["effort"] == claude.EFFORT
    content = call["messages"][0]["content"]
    images = [b for b in content if b["type"] == "image"]
    assert len(images) == 2  # both board photos, as photo ingest sent them
    with closing(connect(store.db)) as conn:
        sent = {r[0] for r in conn.execute("SELECT sent_sha256 FROM model_run")}
    assert {b["source"]["sha256"] for b in images} == sent
    assert call["blob"](images[0]["source"]["sha256"])[1] == "image/jpeg"
    page = store.page(ref["page_id"])
    up = page["writeup"]["current"]
    assert up["producer"] == claude.model_name() and up["version"] == 1
    assert up["prompt_version"].startswith("writeup@")
    assert page["writeup"]["board"] is True and page["writeup"]["state"] == "done"
    assert page["body"] == "\n\n".join(
        f"![](/api/blobs/{b['sha256']}/preview?size=2048)"
        for b in page["captures"][0]["blobs"]
    )  # the text is never touched
    assert other["page_id"] in [r["id"] for r in page["related"]]


@pytest.mark.parametrize("answer", [STICKY, SCENE, {**BOARD, "kind": "document"}])
def test_a_to_do_sticky_or_a_photo_gets_no_write_up_but_its_related_call(store, answer):
    ref = photo(store)
    fake = Fake(photo=answer)
    run_all(store, fake)
    assert "writeup" not in fake.kinds()
    assert jobs(store) == [("related", "done")]  # as before (#258)
    assert store.page(ref["page_id"])["writeup"] is None


def test_with_enrich_off_nothing_is_queued(store, monkeypatch):
    monkeypatch.setenv("SCRAP_ENRICH", "off")
    ref = photo(store)
    run_all(store, Fake())
    assert jobs(store) == []
    view = store.page(ref["page_id"])["writeup"]
    assert view["board"] is True and view["on"] is False and view["current"] is None


def test_reprocess_of_a_board_image_writes_it_up_again(store):
    ref = board_page(store)
    assert jobs(store) == [("writeup", "done"), ("related", "done")]
    time.sleep(0.002)  # stamps are to the millisecond
    ingest.reprocess(store, ref["capture_id"], None, False)
    fake = Fake(writeup={"summary": "Again.", "text": "## Overview\n\nagain"})
    run_all(store, fake)
    assert fake.kinds() == ["photo", "writeup"]  # its first related call is had
    assert store.page(ref["page_id"])["writeup"]["current"]["version"] == 2
    # the nightly pass picks related pages again: the write-up is newer than them
    assert enrich.related_pass(store, fake, dry_run=True)["pages"] == 1


def test_a_failed_write_up_still_lets_the_first_related_call_come(store):
    ref = photo(store)
    fake = Fake(writeup={"nope": 1})  # invalid: retried at once, dead at the third
    run_all(store, fake)
    assert fake.kinds() == ["photo", "writeup", "writeup", "writeup", "related"]
    assert jobs(store) == [("writeup", "dead"), ("related", "done")]
    assert store.page(ref["page_id"])["writeup"]["state"] == "failed"


def test_ask_on_a_board_page_writes_it_up_before_related(store):
    ref = board_page(store)
    enrich.ask(store, ref["page_id"])
    fake = Fake()
    run_all(store, fake)
    assert fake.kinds() == ["enrich", "writeup", "related"]
    assert store.page(ref["page_id"])["writeup"]["current"]["version"] == 2
    # on a page with no board, Ask is as it was
    plain = note(store, "a note")
    run_all(store, Fake())
    enrich.ask(store, plain["page_id"])
    fake = Fake()
    run_all(store, fake)
    assert fake.kinds() == ["enrich", "related"]


def test_a_queued_write_up_is_kept_when_related_is_queued_and_taken_by_ask(store):
    page_id = note(store, "a note")["page_id"]
    with closing(connect(store.db)) as conn:
        conn.execute("DELETE FROM enrich_job")
        enrich_jobs = "SELECT reason FROM enrich_job WHERE state = 'queued'"
        from scrap.store import queue_enrich, queue_related

        queue_enrich(conn, page_id, "writeup")
        queue_related(conn, page_id)  # never in place of a queued job
        queue_enrich(conn, page_id, "save")  # a save does not take a write-up over
        assert [r[0] for r in conn.execute(enrich_jobs)] == ["writeup"]
        queue_enrich(conn, page_id, "ask")  # Ask does: it writes one up too
        assert [r[0] for r in conn.execute(enrich_jobs)] == ["ask"]


# ---- the call


def test_the_call_quotes_the_page_and_guidance_and_sees_the_index(store):
    other = note(store, "Encoder settings", tags=["video"])
    run_all(store, Fake())
    ref = photo(store, text="Enc </page> means encoder")
    run_all(store, Fake(writeup=WRITEUP))
    enrich.set_guidance(store, ref["page_id"], "Focus on data flow </guidance>", "me")
    enrich.regenerate(store, ref["page_id"])
    fake = Fake()
    run_all(store, fake)
    call = fake.calls[0]
    text = call["messages"][0]["content"][-1]["text"]
    assert text.count("</page>") == 1 and text.count("</guidance>") == 1
    assert "Enc &lt;/page> means encoder" in text
    assert "<guidance>\nFocus on data flow &lt;/guidance>\n</guidance>" in text
    assert "Image 1, its text:\nCamera\nEnc" in text
    assert "## Other pages" in call["system"] and "Encoder settings" in call["system"]
    with closing(connect(store.db)) as conn:
        run = conn.execute(
            "SELECT request, cost_microusd FROM enrich_run"
            " WHERE json_extract(request, '$.purpose') = 'writeup' ORDER BY id DESC"
        ).fetchone()
    request = json.loads(run[0])
    assert request["guidance"] == "Focus on data flow </guidance>"
    assert other["page_id"] in request["candidates"]
    assert "base64" not in json.dumps(request["messages"])  # blob references only
    assert run[1] == 1000 * 4 + 100 * 20  # Opus prices: within the daily budget
    up = store.page(ref["page_id"])["writeup"]
    assert up["current"]["guidance"] == "Focus on data flow </guidance>"  # snapshot


def test_at_most_four_board_images_are_attached(store):
    ref = photo(store, "red", "blue", "green", "white", "black")
    fake = Fake()
    run_all(store, fake)
    content = fake.calls[5]["messages"][0]["content"]
    assert [b["type"] for b in content].count("image") == enrich.MAX_BOARDS
    assert "Images attached: 1, 2, 3, 4" in content[-1]["text"]
    assert "Image 5, its text" in content[-1]["text"]
    assert store.page(ref["page_id"])["writeup"]["current"] is not None


def test_cited_numbers_become_page_links_and_others_are_dropped():
    slugs = ["enc-settings", "camera-notes"]
    text = (
        "See [[1]], [[2|the camera]], [[3]], [[0|zero]], [[made-up-page]],"
        " [[made-up|words]] and [[ 2 ]]."
    )
    assert enrich.cited(text, slugs) == (
        "See [[enc-settings]], [[camera-notes|the camera]], , zero, ,"
        " words and [[camera-notes]]."
    )
    out = enrich.checked_writeup(
        {"summary": "Two\nlines\x07.", "text": "## A\r\n[web](https://x.example)"
         " ![img](https://x.example/p.png) [[1]]\x00"},
        slugs,
    )  # fmt: skip
    assert out == {"summary": "Two lines .", "text": "## A\nweb img [[enc-settings]]"}
    with pytest.raises(ValueError):
        enrich.checked_writeup({"summary": "s", "text": " [[9]] "}, slugs)
    with pytest.raises(ValueError):
        enrich.checked_writeup({"summary": "s"}, slugs)


def test_the_call_links_only_pages_it_was_given(store):
    other = note(store, "Encoder settings", tags=["video"])
    run_all(store, Fake())
    slug = store.page(other["page_id"])["slug"]

    def answer(system):
        index = system.split("## Other pages")[1]
        n = next(int(x.split(".")[0]) for x in index.splitlines() if "Encoder" in x)
        return {"summary": "s", "text": f"Uses [[{n}|the settings]] and [[999]]."}

    ref = board_page(store, Fake(writeup=answer))
    up = store.page(ref["page_id"])["writeup"]["current"]
    assert up["text"] == f"Uses [[{slug}|the settings]] and ."


# ---- summary, search and Related


def test_the_write_up_is_the_summary_of_a_board_page(store):
    ref = board_page(store)
    with closing(connect(store.db)) as conn:
        assert model_summary(conn, ref["page_id"]) == WRITEUP["summary"]
        conn.execute(
            "INSERT INTO enrichment (page_id, producer, summary, updated_at)"
            " VALUES (?, 'claude-haiku-5-5', 'From enrich.', ?)",
            (ref["page_id"], now()),
        )
        assert model_summary(conn, ref["page_id"]) == WRITEUP["summary"]
    # a page with no write-up keeps enrich's
    text = note(store, "a note")["page_id"]
    with closing(connect(store.db)) as conn:
        conn.execute(
            "INSERT INTO enrichment (page_id, producer, summary, updated_at)"
            " VALUES (?, 'claude-haiku-5-5', 'From enrich.', ?)",
            (text, now()),
        )
        assert model_summary(conn, text) == "From enrich."
    assert [h["id"] for h in store.search("pipeline camera store", 10)] == [
        ref["page_id"]
    ]


def test_write_up_text_is_searched_and_not_its_link_targets(store):
    target = note(store, "Encoder settings", tags=["video"])
    run_all(store, Fake())
    slug = store.page(target["page_id"])["slug"]

    def answer(system):
        index = system.split("## Other pages")[1]
        n = next(int(x.split(".")[0]) for x in index.splitlines() if "Encoder" in x)
        return {"summary": "s", "text": f"Zanzibar flows into [[{n}|the quokka]]."}

    ref = board_page(store, Fake(writeup=answer))
    assert [h["id"] for h in store.search("zanzibar", 10)] == [ref["page_id"]]
    hit = store.search("quokka", 10)[0]
    assert hit["id"] == ref["page_id"] and "<mark>quokka</mark>" in hit["snippet"]
    assert slug not in [h["slug"] for h in store.search("zanzibar", 10)]
    # the chunk is made again with the page's own
    store.update_page(ref["page_id"], 1, "Renamed board", None, "me")
    assert [h["id"] for h in store.search("zanzibar", 10)] == [ref["page_id"]]


def test_write_up_links_show_in_related_both_ways(store):
    target = note(store, "Encoder settings", tags=["video"])
    run_all(store, Fake())

    def answer(system):
        index = system.split("## Other pages")[1]
        n = next(int(x.split(".")[0]) for x in index.splitlines() if "Encoder" in x)
        return {"summary": "s", "text": f"See [[{n}]]."}

    ref = board_page(store, Fake(writeup=answer))  # its related call picks none
    there = store.page(ref["page_id"])
    assert [(r["id"], r["via"]) for r in there["related"]] == [
        (target["page_id"], "writeup")
    ]
    back = store.page(target["page_id"])["related"]
    assert [(r["id"], r["via"]) for r in back] == [(ref["page_id"], "writeup")]
    slug = store.page(target["page_id"])["slug"]
    assert store.backlinks(slug) == []  # not the body's backlinks
    with closing(connect(store.db)) as conn:  # picked too: shown once, Claude's pick
        conn.execute(
            "INSERT INTO related VALUES (?, ?, 0)", (ref["page_id"], target["page_id"])
        )
    there = store.page(ref["page_id"])
    assert [(r["id"], r["via"]) for r in there["related"]] == [
        (target["page_id"], "claude")
    ]


# ---- the migration


def test_migration_12_on_a_v11_database_keeps_jobs_and_runs(store):
    """A database as 0.6.0 left it: no write-up tables, no 'writeup' reason."""
    note(store, "a note")
    run_all(store, Fake())
    with closing(sqlite3.connect(store.db)) as conn:  # foreign keys off: as it was
        conn.executescript(
            "BEGIN; DROP TABLE writeup; DROP TABLE writeup_guidance;"
            " CREATE TABLE old AS SELECT * FROM enrich_job; DROP TABLE enrich_job;"
            + fixes.ENRICH_JOB.format(name="enrich_job").replace(", 'writeup'", "")
            + "; INSERT INTO enrich_job SELECT * FROM old; DROP TABLE old;"
            + fixes.ENRICH_JOB_INDEXES
            + " PRAGMA user_version = 11; COMMIT;"
        )
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'enrich_job'")
        assert "'writeup'" not in sql.fetchone()[0]
    before = jobs(store)
    store.migrate()
    assert jobs(store) == before
    with closing(connect(store.db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
        assert len(migrations()) >= 14
        runs = [tuple(r) for r in conn.execute(
            "SELECT r.job_id, j.reason FROM enrich_run r JOIN enrich_job j"
            " ON j.id = r.job_id ORDER BY r.id")]  # fmt: skip
        assert runs == [(1, "capture"), (2, "related")]
        fixes.add_writeups(conn)  # again: nothing to do
        page_id = conn.execute("SELECT id FROM page").fetchone()[0]
        conn.execute("DELETE FROM enrich_job")
        conn.execute(  # the new reason is taken, and the tables are there
            "INSERT INTO enrich_job (page_id, reason, run_after, created_at,"
            " updated_at) VALUES (?, 'writeup', '', '', '')",
            (page_id,),
        )
        assert writeups.versions(conn, page_id) == []


# ---- the CLI, the API and MCP


def test_the_cli_makes_write_ups_for_board_pages_with_none(
    tmp_path, capsys, monkeypatch
):
    from scrap.__main__ import main

    store = Store(tmp_path)
    store.migrate()
    monkeypatch.setenv("SCRAP_ENRICH", "off")  # read, but no write-up queued
    photo(store)
    photo(store)
    run_all(store, Fake())
    photo(store)
    run_all(store, Fake(photo=SCENE))
    monkeypatch.delenv("SCRAP_ENRICH")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    main(["enrich", "--writeups", "--dry-run", "--data-dir", str(tmp_path)])
    assert "would write up 2 board pages" in capsys.readouterr().out
    fake = Fake()
    assert enrich.writeup_pass(store, fake, limit=1)["done"] == 1
    main(["enrich", "--writeups", "--dry-run", "--data-dir", str(tmp_path)])
    assert "would write up 1 board pages" in capsys.readouterr().out
    main(["enrich", "--writeups", "--all", "--dry-run", "--data-dir", str(tmp_path)])
    assert "would write up 2 board pages" in capsys.readouterr().out
    monkeypatch.setenv("SCRAP_INGEST", "off")
    main(["enrich", "--writeups", "--data-dir", str(tmp_path)])
    assert "write-ups: Claude enrichment is off" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["enrich", "--writeups", "--related", "--data-dir", str(tmp_path)])


def test_the_write_up_pass_stops_at_a_pause_and_the_budget(store, monkeypatch):
    monkeypatch.setenv("SCRAP_ENRICH", "off")
    photo(store)
    photo(store)
    run_all(store, Fake())
    monkeypatch.delenv("SCRAP_ENRICH")
    outage = claude.CallError("outage", "busy")
    counts = enrich.writeup_pass(store, Fake(writeup=outage))
    assert counts == {"pages": 2, "done": 0, "failed": 0, "stopped": "outage"}
    with closing(connect(store.db)) as conn:
        ingest.resume(conn, now())
    monkeypatch.setenv("SCRAP_BUDGET_DAY_USD", "0")
    counts = enrich.writeup_pass(store, Fake())
    assert counts["stopped"] == "budget" and counts["done"] == 0


def test_the_api_regenerates_steers_lists_and_restores(tmp_path, monkeypatch):
    client = TestClient(create_app(tmp_path / "data"))
    store = Store(tmp_path / "data")
    ref = board_page(store)
    text = note(store, "a note")
    key = ref["page_id"]
    assert client.post(f"/api/pages/{text['page_id']}/writeup").status_code == 422
    got = client.put(f"/api/pages/{key}/writeup/guidance",
                     json={"guidance": "  'Enc' means encoder "})  # fmt: skip
    assert got.status_code == 200 and got.json()["writeup"]["guidance"] == (
        "'Enc' means encoder"
    )
    too_long = {"guidance": "x" * (enrich.MAX_GUIDANCE + 1)}
    got = client.put(f"/api/pages/{key}/writeup/guidance", json=too_long)
    assert got.status_code == 422
    page = client.post(f"/api/pages/{key}/writeup").json()
    assert page["writeup"]["state"] == "queued"
    run_all(store, Fake())
    versions = client.get(f"/api/pages/{key}/writeup/versions").json()
    assert [(v["version"], v["current"]) for v in versions] == [(2, True), (1, False)]
    assert versions[0]["guidance"] == "'Enc' means encoder"
    assert versions[1]["guidance"] is None
    stale = client.post(f"/api/pages/{key}/writeup/restore",
                        json={"version": 1, "base_version": 1})  # fmt: skip
    assert stale.status_code == 409 and stale.json()["version"] == 2
    missing = client.post(f"/api/pages/{key}/writeup/restore",
                          json={"version": 7, "base_version": 2})  # fmt: skip
    assert missing.status_code == 404
    page = client.post(f"/api/pages/{key}/writeup/restore",
                       json={"version": 1, "base_version": 2}).json()  # fmt: skip
    assert page["writeup"]["current"]["restored_from"] == 1
    cleared = client.put(f"/api/pages/{key}/writeup/guidance", json={"guidance": ""})
    assert cleared.json()["writeup"]["guidance"] is None
    monkeypatch.setenv("SCRAP_ENRICH", "off")
    assert client.post(f"/api/pages/{key}/writeup").status_code == 409
    assert client.get(f"/api/pages/{text['page_id']}").json()["writeup"] is None


def test_mcp_read_returns_the_write_up_under_by_model(store):
    ref = board_page(store)

    async def main():
        async with Client(mcp_server.server(store)) as client:
            return await client.call_tool("read", {"page": ref["slug"]})

    by = anyio.run(main).structured_content["by_model"]
    up = by["writeup"]
    assert up["summary"] == WRITEUP["summary"] and up["text"].startswith("## Overview")
    assert up["version"] == 1 and up["producer"] == claude.model_name()
    assert up["created_at"] and by["summary"] == WRITEUP["summary"]


def test_no_link_but_a_mapped_page_link_survives():
    """Whatever Markdown or linkify would make a link of, the words stay, unlinked."""
    text = (
        "## A\nSee https://evil.example/x, <https://a.example>, <me@x.example> and"
        " mailto:me@x.example.\nRef [click][r], [other][] and ![img][i]; [[1]].\n"
        "[r]: https://evil.example\n  [other]: /p/secret-page\n[i]: <https://x/i.png>\n"
        "Kept[^1].\n\n[^1]: a footnote"
    )
    out = enrich.checked_writeup({"summary": "s", "text": text}, ["enc"])["text"]
    assert out == (
        "## A\nSee evil.example/x, a.example, me@x.example and me@x.example.\n"
        "Ref click, other and img; [[enc]].\nKept[^1].\n\n[^1] : a footnote"
    )  # a footnote is split from its text too: no "]:" is left to define anything
    assert "://" not in out and "/p/" not in out and "mailto" not in out


def test_a_page_no_longer_a_board_keeps_its_write_up_unseen(store):
    target = note(store, "Encoder settings", tags=["video"])
    run_all(store, Fake())

    def answer(system):
        index = system.split("## Other pages")[1]
        n = next(int(x.split(".")[0]) for x in index.splitlines() if "Encoder" in x)
        return {"summary": "Zanzibar lead.", "text": f"Zanzibar, see [[{n}]]."}

    ref = board_page(store, Fake(writeup=answer))
    assert [h["id"] for h in store.search("zanzibar", 10)] == [ref["page_id"]]
    time.sleep(0.002)
    ingest.reprocess(store, ref["capture_id"], None, False)
    run_all(store, Fake(photo=SCENE))  # read again: a photo of a scene now
    page = store.page(ref["page_id"])
    assert page["writeup"] is None
    assert "writeup" not in [r["via"] for r in page["related"]]
    assert "writeup" not in [r["via"] for r in store.page(target["page_id"])["related"]]
    assert store.search("zanzibar", 10) == []
    with closing(connect(store.db)) as conn:
        assert model_summary(conn, ref["page_id"]) == ""
        assert len(writeups.versions(conn, ref["page_id"])) == 1  # kept, as history
    with pytest.raises(Exception, match="whiteboard or diagram"):
        enrich.regenerate(store, ref["page_id"])


def test_an_ask_retried_after_its_related_call_does_not_write_up_again(store):
    ref = board_page(store)
    enrich.ask(store, ref["page_id"])
    fake = Fake()
    failed = []

    def call(model, system, messages, schema, blob, **kw):
        if schema is enrich.RELATED_SCHEMA and not failed:
            failed.append(1)  # invalid output: retried at once
            fake.calls.append({"kind": "related"})
            raise claude.CallError("invalid", "not an answer")
        return fake(model, system, messages, schema, blob, **kw)

    run_all(store, call)
    assert fake.kinds() == ["enrich", "writeup", "related", "enrich", "related"]
    assert jobs(store)[-1] == ("ask", "done")
    assert store.page(ref["page_id"])["writeup"]["current"]["version"] == 2


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        # dropping a bad citation leaves a definition behind: it goes too
        ("[r]\n\n[[zz]][r]: /p/evil-page", "[r]"),
        # taking out one scheme leaves another
        ("x https:a:////evil.example/x", "x evil.example/x"),
        # nested: a citation's words, a link around one, a definition after one
        (
            "[[1|see https://e.example]] [w]([[1]]) [[1]]: /p/evil [[1]](/p/evil)"
            " [a\\]b]: /p/evil [x]( /p/evil ) [[ [[9]] ]]",
            "[[enc|see e.example]] w [[enc]] : /p/evil [[enc]] (/p/evil)"
            " [a\\]b] : /p/evil [x] ( /p/evil )",
        ),
    ],
    ids=["dropped-citation-leaves-a-definition", "one-scheme-leaves-another", "nested"],
)
def test_stripping_one_link_never_leaves_another(text, kept):
    out = enrich.cited(text, ["enc"])
    assert out.strip() == kept
    assert "](" not in out.replace("]] (", "") and "]:" not in out
    assert "://" not in out


# Inputs that would be quadratic in an unbounded pattern, made in the test: as
# parameters they would be the test ids, 100k characters each in every report line,
# whose reporting alone slowed the other workers' timing tests (#269)
PATHOLOGICAL = {
    "dots": lambda: "a." * 50_000,
    "scheme-run": lambda: "a" * 100_000 + ":",
    "open-autolink": lambda: "<" + "a" * 100_000,
    "brackets": lambda: "[" * 50_000 + "](",
}


@pytest.mark.timing  # run alone: see conftest.py
@pytest.mark.parametrize("name", list(PATHOLOGICAL))
def test_stripping_a_pathological_write_up_is_quick(name):
    """Linear, not quadratic: the unbounded pattern took about 10 s on 64k characters;
    a generous bound keeps a slow runner from failing it."""
    bad = PATHOLOGICAL[name]()
    start = time.perf_counter()
    enrich.cited(bad, ["enc"])  # all of it, uncut
    enrich.checked_writeup({"summary": "s", "text": bad + " x"}, ["enc"])
    took = time.perf_counter() - start
    assert took < 5.0, f"{name}: {took:.1f} s"  # no input in the message
