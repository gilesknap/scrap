# pyright: reportOptionalSubscript=false
"""A failed model call's run row (#499), at each call site: a refusal, output that
fails its check (invalid) and any other CallError (error), each recorded with its
class, message and, when there was a response, its model, usage and cost."""

import io
import json
from contextlib import closing
from typing import Any

import pytest
from PIL import Image

from scrap import claude, enrich, ingest, runs
from scrap.store import Store, connect, new_ulid, now, topics, transaction

SERVED = "claude-test-served"
BOARD = {
    "kind": "whiteboard", "title": "Encoder pipeline", "tags": ["video"],
    "description": "A whiteboard of an encoder pipeline.", "text": "Camera\nEnc",
    "elements": [], "intent": "other", "confidence": "low", "items": [],
}  # fmt: skip


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH_DEBOUNCE", "0")


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    return store


def completion(output: Any, stop_reason: str = "end_turn") -> claude.Completion:
    content = [{"type": "text", "text": json.dumps(output)}]
    usage = {"input_tokens": 1000, "output_tokens": 100}
    return claude.Completion(output, content, usage, SERVED, stop_reason)


class Failing:
    """claude.complete, faked to fail one way: an error raised, output that is not
    an answer (invalid), or a refusal (whose empty output is not one either). good:
    what any call of another schema answers (a photo's reading, enrich's)."""

    def __init__(self, how: str, schema: Any = None, good: Any = None):
        self.how, self.schema, self.good = how, schema, good or {}

    def __call__(self, model, system, messages, schema, blob, **kw):
        if self.schema is not None and schema is not self.schema:
            return completion(self.good.get(id(schema), {}))
        if self.how == "error":
            raise claude.CallError("timeout", "slow")
        if self.how == "invalid":
            return completion({"nope": 1})
        return completion({}, "refusal")


def note(store, text, tags=None):
    c = store.prepare({"id": new_ulid(), "text": text}, [])
    return store.capture(c, [], "me", tags)[0]["page_id"]


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 300), "red").save(out, "JPEG")
    return out.getvalue()


def photo(store) -> str:
    sha, size = store.put_blob(io.BytesIO(jpeg()))
    c = store.prepare({"id": new_ulid(), "text": None}, ["image/jpeg"])
    return store.capture(c, [(sha, "image/jpeg", size, None)], "me")[0]["page_id"]


def last_run(store, table: str) -> dict[str, Any]:
    with closing(connect(store.db)) as conn:
        return dict(
            conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 1").fetchone()
        )


def via_worker(store, how):
    photo(store)
    ingest.Worker(store, Failing(how)).step()
    return "model_run", "ingest"


def via_enricher(store, how):
    note(store, "a note about kafka queues")
    w = ingest.Worker(store, Failing(how))
    w.enrich = True
    assert w.enricher.step()
    return "enrich_run", "enrich"


def via_relate(store, how):
    page = note(store, "a note about kafka queues", ["kafka"])
    note(store, "another about kafka", ["kafka"])
    enrich.relate(store, Failing(how), page)
    return "enrich_run", "related"


def via_write_up(store, how):
    page = photo(store)
    ingest.Worker(store, Failing(how, schema=enrich.WRITEUP_SCHEMA, good={
        id(claude.SCHEMA): BOARD})).step()  # fmt: skip
    enrich.write_up(store, Failing(how), page)
    return "enrich_run", "writeup"


def via_synthesise(store, how):
    sources = [note(store, f"ibek {n}\n\nibek reads YAML") for n in range(2)]
    with closing(connect(store.db)) as conn, transaction(conn):
        topic = topics.create(conn, "ibek", "IBEK", "ibek", "me", now())
        assert topic is not None
        topics.add_sources(conn, topic, sources, "me", now())
    enrich.synthesise(store, Failing(how), topic)
    return "enrich_run", "topic"


def via_discover(store, how):
    note(store, "a note about kafka queues")
    error, _ = enrich.discover(store, Failing(how))
    assert error is not None
    return "topic_run", "topics"


SITES = [via_worker, via_enricher, via_relate, via_write_up, via_synthesise,
         via_discover]  # fmt: skip


@pytest.mark.parametrize("site", SITES, ids=lambda f: f.__name__[4:])
@pytest.mark.parametrize(
    ("how", "status", "error_class"),
    [
        ("error", "error", "timeout"),
        ("invalid", "invalid", "invalid"),
        ("refused", "refused", "invalid"),
    ],  # fmt: skip
)
def test_a_failed_call_is_recorded_on_its_run(store, site, how, status, error_class):
    table, purpose = site(store, how)
    run = last_run(store, table)
    assert run.get("purpose", json.loads(run["request"]).get("purpose")) == purpose
    assert (run["status"], run["error_class"]) == (status, error_class)
    assert run["error"] and len(run["error"]) <= 500 and run["finished_at"]
    if how == "error":  # no response: nothing of one recorded
        assert run["error"] == "slow"
        assert (run["served_model"], run["response"], run["usage"]) == (None,) * 3
    else:
        assert run["served_model"] == SERVED and run["cost_microusd"] is not None
        response = json.loads(run["response"])
        stop = "refusal" if how == "refused" else "end_turn"
        assert response["stop_reason"] == stop
        assert json.loads(run["usage"]) == {"input_tokens": 1000, "output_tokens": 100}
    assert run["output"] is None


def test_the_helpers_start_and_fail_a_run(store):
    with closing(connect(store.db)) as conn, transaction(conn):
        run_id = runs.start_run(
            conn, "topic_run", model="m", prompt_version="v", request="{}"
        )
        row = conn.execute("SELECT * FROM topic_run WHERE id = ?", (run_id,)).fetchone()
        got = (row["model"], row["status"], row["finished_at"])
        assert got == ("m", "running", None)
        assert row["started_at"]
        long = claude.CallError("content", "x" * 600, completion=completion({}))
        runs.failed(conn, "topic_run", run_id, long)
        row = conn.execute("SELECT * FROM topic_run WHERE id = ?", (run_id,)).fetchone()
    got = (row["status"], row["error_class"], len(row["error"]))
    assert got == ("error", "content", 500)
    assert row["served_model"] == SERVED and row["finished_at"]


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (claude.CallError("outage", "busy"), "error"),
        (claude.CallError("invalid", "bad"), "invalid"),
        (
            claude.CallError("invalid", "bad", completion=completion({}, "refusal")),
            "refused",
        ),
        (
            claude.CallError("content", "no", completion=completion({}, "refusal")),
            "refused",
        ),
        (claude.CallError("content", "no", completion=completion({})), "error"),
    ],  # fmt: skip
)
def test_a_failure_s_status(error, status):
    assert runs.status(error) == status
