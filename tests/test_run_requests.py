# pyright: reportOptionalSubscript=false
"""What an enrich or topic run's stored request keeps of its system prompt (#571):
its SHA-256 and length, not the text (the related pass's was ~35 KB a row); and
what reads stored requests works with old rows that kept the text."""

import hashlib
import io
import json
from contextlib import closing
from typing import Any

import pytest
from PIL import Image

from fakeclaude import FakeClaude, run_all
from scrap import enrich, retention, runs
from scrap.enrich import relating
from scrap.store import Store, connect, new_ulid, now, topics, transaction

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


class Fake(FakeClaude):
    """claude.complete, faked: each kind answered, each call's system kept."""

    schemas = ("photo", "writeup", "topic", "discovery", "related")

    def answer(self, kind, system, messages):
        return {
            "photo": BOARD, "writeup": WRITEUP, "topic": SYNTHESIS,
            "discovery": {"new": [], "add": []}, "related": {"related": []},
        }[kind]  # fmt: skip


def note(store, text, tags=None):
    c = store.prepare({"id": new_ulid(), "text": text}, [])
    return store.capture(c, [], "me", tags)[0]["page_id"]


def photo(store) -> str:
    out = io.BytesIO()
    Image.new("RGB", (400, 300), "red").save(out, "JPEG")
    sha, size = store.put_blob(io.BytesIO(out.getvalue()))
    c = store.prepare({"id": new_ulid(), "text": None}, ["image/jpeg"])
    return store.capture(c, [(sha, "image/jpeg", size, None)], "me")[0]["page_id"]


def requests(store, table: str) -> list[dict[str, Any]]:
    with closing(connect(store.db)) as conn:
        return [json.loads(r[0]) for r in conn.execute(
            f"SELECT request FROM {table} ORDER BY id")]  # fmt: skip


def digest(system: str) -> tuple[str, int]:
    return hashlib.sha256(system.encode()).hexdigest(), len(system)


def test_every_pass_keeps_its_prompt_s_digest_not_its_text(store):
    pages = [note(store, f"ibek {w}\n\nibek reads YAML", ["epics"])
             for w in ("yaml", "schema")]  # fmt: skip
    board = photo(store)
    fake = Fake()
    run_all(store, fake)  # photo, enrich, related, a board's write-up
    with closing(connect(store.db)) as conn, transaction(conn):
        topic = topics.create(conn, "ibek", "IBEK", "ibek", "me", now())
        assert topic is not None
        topics.add_sources(conn, topic, pages, "me", now())
    assert enrich.synthesise(store, fake, topic) is None
    assert enrich.write_up(store, fake, board) is None
    error, _ = enrich.discover(store, fake)
    assert error is None
    sent = {digest(c["system"]) for c in fake.calls}
    stored = requests(store, "enrich_run") + requests(store, "topic_run")
    purposes = {r["purpose"] for r in stored}
    assert purposes == {"enrich", "related", "writeup", "topic", "topics"}
    for request in stored:
        assert "system" not in request
        assert (request["system_sha256"], request["system_len"]) in sent
    # the photo's reading keeps its fixed prompt (model_run, out of #571)
    assert all("system" in r for r in requests(store, "model_run"))


def test_a_related_run_s_request_is_small_with_many_candidates(store, monkeypatch):
    about = "a candidate page's summary, as the related prompt shows it. " * 4
    many = [{"id": new_ulid(), "title": f"Candidate page {n}", "tags": ["kafka"],
             "summary": about} for n in range(150)]  # fmt: skip
    monkeypatch.setattr(relating, "CANDIDATES", lambda conn, page_id: many)
    page = note(store, "a note about kafka queues", ["kafka"])
    fake = Fake()
    assert enrich.relate(store, fake, page) is None
    [call] = [c for c in fake.calls if c["kind"] == "related"]
    [request] = [r for r in requests(store, "enrich_run") if r["purpose"] == "related"]
    assert len(call["system"]) > 25_000  # the prompt sent: every candidate in it
    assert "system" not in request
    assert (request["system_sha256"], request["system_len"]) == digest(call["system"])
    assert request["candidates"] == [p["id"] for p in many]
    assert len(json.dumps(request)) < 8_000  # the ids, the message and the schema


def test_old_rows_that_kept_the_prompt_still_count(store):
    """An enrich_run row from before #571 keeps `system` and has no digest: the
    readers of stored requests (by purpose) treat it as any other."""
    page = note(store, "a note about kafka queues", ["kafka"])
    note(store, "another about kafka", ["kafka"])
    run_all(store, Fake())
    with closing(connect(store.db)) as conn, transaction(conn):
        conn.execute(
            "UPDATE enrich_run SET request = json_set(json_remove(request,"
            " '$.system_sha256', '$.system_len'), '$.system', ?)",
            ("# the prompt, kept whole\n" * 1000,),
        )
        due = {r[0] for r in conn.execute(enrich.STALE, {"all": False, "limit": -1})}
        assert page not in due  # picked: its newest ok related run is found
        newest = conn.execute(
            "SELECT max(id) FROM enrich_run WHERE page_id = ?"
            " AND json_extract(request, '$.purpose') = 'related'", (page,)
        ).fetchone()[0]  # fmt: skip
        runs.start_run(conn, "enrich_run", page_id=page, status="ok", model="m",
                       prompt_version="v",
                       request=json.dumps({"purpose": "enrich"}))  # fmt: skip
        conn.execute("UPDATE enrich_run SET started_at = '2000-01-01T00:00:00Z'")
        retention.prune_runs(conn, 30, delete=True)
        kept = {r[0] for r in conn.execute("SELECT id FROM enrich_run")}
    assert newest in kept  # kept as the newest ok related run, not the page's newest
