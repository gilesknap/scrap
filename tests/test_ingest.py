# pyright: reportOptionalSubscript=false
"""The ingest queue, the worker (Claude faked), versions, page fields and search."""

import io
import json
import sqlite3
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from scrap import claude, ingest, spend
from scrap.app import create_app
from scrap.ingest import FAR, charge, claim, pause, put_derived, recover, resume
from scrap.store import ENQUEUE, Store, connect, migrations, new_ulid, transaction

T0 = datetime(2099, 1, 1, tzinfo=UTC)  # after the jobs the tests make


PAST = "2000-01-01T00:00:00.000Z"


def at(minutes: float) -> str:
    t = T0 + timedelta(minutes=minutes)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def jpeg(colour="red", size=(400, 300)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    return store


@pytest.fixture
def conn(store):
    with closing(connect(store.db)) as conn:
        yield conn


def photo(store, images=(b"a",), text=None, mime="image/jpeg"):
    """Capture a photo of the given images (bytes, stored for real); its reference."""
    blobs = []
    for data in images:
        sha, size = store.put_blob(io.BytesIO(data))
        blobs.append((sha, mime, size, None))
    c = store.prepare({"id": new_ulid(), "text": text}, [mime] * len(blobs))
    return store.capture(c, blobs, "me")[0]


def shas(conn, capture_id):
    return [
        r[0]
        for r in conn.execute(
            "SELECT source_sha256 FROM job WHERE capture_id = ? ORDER BY id",
            (capture_id,),
        )
    ]


def job(conn, jid=1):
    row = conn.execute(
        "SELECT state, failures, last_error FROM job WHERE id = ?", (jid,)
    ).fetchone()
    return row[0], row[1], (row[2] or "").split(":")[0]


def outcome(conn, j, cls, stamp):
    """The worker's bookkeeping for a call that failed with cls, or succeeded."""
    with transaction(conn):
        if cls == "ok":
            conn.execute("UPDATE job SET state = 'done' WHERE id = ?", (j["id"],))
            resume(conn, stamp)
        elif cls in ingest.PAUSES:
            pause(conn, j["id"], cls, stamp)
        else:
            charge(conn, j["id"], cls, stamp, "boom")


# ---- migration


def test_0002_applies_on_a_version_1_database(tmp_path):
    db = tmp_path / "scrap.db"
    with closing(connect(db)) as conn:
        conn.executescript(f"BEGIN; {migrations()[0]} PRAGMA user_version = 1; COMMIT;")
        conn.execute("INSERT INTO page (id, slug, title, created_at, updated_at)"
                     " VALUES ('P', 'p', 't', 'x', 'x')")  # fmt: skip
        conn.execute("INSERT INTO chunk (page_id, ord, text) VALUES ('P', 0, 'old')")
    Store(tmp_path).migrate()
    with closing(connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
        assert conn.execute("SELECT derived_id FROM chunk").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM queue_state").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


# ---- enqueue


def test_a_photo_capture_queues_each_distinct_image(store, conn):
    ref = photo(store, [b"a", b"a", b"b"])  # the same photo twice is no error
    assert len(shas(conn, ref["capture_id"])) == 2
    conn.execute(ENQUEUE, {"capture": ref["capture_id"], "photo": None,
                           "options": "{}", "now": at(0)})  # fmt: skip
    assert len(shas(conn, ref["capture_id"])) == 2  # already queued: nothing added


def test_files_notes_and_non_images_are_not_queued(store, conn):
    pdf = photo(store, [b"pdf"], mime="application/pdf")
    assert shas(conn, pdf["capture_id"]) == []
    note = store.capture(store.prepare({"id": new_ulid(), "text": "hi"}, []), [], "me")
    assert shas(conn, note[0]["capture_id"]) == []
    odd = photo(store, [b"d"])  # a non-image forced in beside a photo
    conn.execute("INSERT INTO blob VALUES (?, 'application/zip', 1, 'x')", ("e" * 64,))
    conn.execute("INSERT INTO capture_blob VALUES (?, 1, ?, NULL)",
                 (odd["capture_id"], "e" * 64))  # fmt: skip
    conn.execute(ENQUEUE, {"capture": odd["capture_id"], "photo": None,
                           "options": "{}", "now": at(0)})  # fmt: skip
    assert len(shas(conn, odd["capture_id"])) == 1


def test_asking_for_one_image_of_a_file_capture_queues_it(store, conn):
    ref = photo(store, [b"x"])
    conn.execute("UPDATE capture SET kind = 'file'")  # e.g. a photo beside a PDF
    conn.execute("DELETE FROM job")
    args = {"capture": ref["capture_id"], "options": "{}", "now": at(0)}
    conn.execute(ENQUEUE, {**args, "photo": None})
    assert shas(conn, ref["capture_id"]) == []  # not sent to Claude unasked
    sha = store.page(ref["page_id"])["captures"][0]["blobs"][0]["sha256"]
    conn.execute(ENQUEUE, {**args, "photo": sha})
    assert shas(conn, ref["capture_id"]) == [sha]


def test_reprocess_and_retry_through_the_api(tmp_path):
    client = TestClient(create_app(tmp_path))
    files = [("file", ("b.jpg", jpeg(), "image/jpeg"))]
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
    url = f"/api/captures/{ref['capture_id']}/reprocess"
    assert client.post(url, json={}).json() == {"queued": 0, "already": 1}
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    blob = page["captures"][0]["blobs"][0]
    assert blob["ingest"]["state"] == "queued" and page["tags"] == []
    with closing(connect(tmp_path / "scrap.db")) as conn:
        conn.execute("UPDATE job SET state = 'dead', last_error = 'image: bad'")
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert page["captures"][0]["blobs"][0]["ingest"]["state"] == "failed"
    one = {"photo": blob["sha256"]}
    assert client.post(url, json=one).json() == {"queued": 1, "already": 0}  # Retry
    assert (
        client.post(f"/api/captures/{new_ulid()}/reprocess", json={}).status_code == 404
    )
    assert client.get("/api/ingest").json()["jobs"] == {"dead": 1, "queued": 1}


# ---- claim


def test_claim_skips_a_paused_queue_and_the_trash(store, conn):
    a, b = photo(store, [b"a"]), photo(store, [b"b"])
    conn.execute("UPDATE queue_state SET paused_until = ?, reason = 'auth'", (FAR,))
    assert claim(conn, at(1)) is None
    resume(conn, at(1))
    store.delete_page(a["page_id"])
    assert claim(conn, at(1))["capture_id"] == b["capture_id"]
    assert claim(conn, at(1)) is None
    store.delete_page(a["page_id"], undo=True)
    assert claim(conn, at(1))["capture_id"] == a["capture_id"]


def _claim_all(db: str) -> list[int]:
    got = []
    with closing(connect(db)) as conn:
        while (j := claim(conn, ingest.now())) is not None:
            got.append(j["id"])
    return got


def test_each_job_is_claimed_once_across_threads_and_processes(store):
    for n in range(40):
        photo(store, [bytes([n])])
    with ThreadPoolExecutor(4) as threads:
        by_thread = list(threads.map(_claim_all, [str(store.db)] * 4))
    claimed = [j for got in by_thread for j in got]
    assert sorted(claimed) == list(range(1, 41))
    with closing(connect(store.db)) as conn:
        conn.execute("UPDATE job SET state = 'queued'")
    with ProcessPoolExecutor(4) as processes:
        by_process = list(processes.map(_claim_all, [str(store.db)] * 4))
    claimed = [j for got in by_process for j in got]
    assert sorted(claimed) == list(range(1, 41))


# ---- the outcome rules


def test_a_poison_job_dies_after_three_timeouts_without_pausing(store, conn):
    photo(store, [b"a"])
    photo(store, [b"b"])
    first = claim(conn, at(0))
    outcome(conn, first, "timeout", at(4))
    second = claim(conn, at(4))  # the other job goes next
    assert second["id"] == 2
    outcome(conn, second, "ok", at(5))
    assert claim(conn, at(13)) is None  # retried 10 minutes after the failure
    for t in (15, 30):
        outcome(conn, claim(conn, at(t)), "timeout", at(t + 4))
    assert job(conn) == ("dead", 3, "timeout")
    assert conn.execute("SELECT paused_until FROM queue_state").fetchone()[0] is None


def test_an_outage_refunds_and_a_spend_limit_parks_until_resume(store, conn):
    photo(store, [b"a"])
    t, claims = 0.0, 0
    while t < 120:  # two hours of 5xx
        j = claim(conn, at(t))
        if j is None:
            t += 0.5
            continue
        claims += 1
        outcome(conn, j, "outage", at(t + 0.25))
    assert claims >= 7 and job(conn) == ("queued", 0, "outage")
    outcome(conn, claim(conn, at(t + 60)), "credit", at(t + 60))
    assert claim(conn, at(t + 60 * 24 * 30)) is None  # a month later: still paused
    resume(conn, at(0))
    j = claim(conn, at(t + 60 * 24 * 30))
    outcome(conn, j, "ok", at(t + 60 * 24 * 30))
    assert job(conn) == ("done", 0, "credit")


def test_after_a_pause_older_jobs_go_first(store, conn):
    for data in (b"a", b"b", b"c"):
        photo(store, [data])
    outcome(conn, claim(conn, at(1)), "outage", at(2))  # paused until at(3)
    assert claim(conn, at(2.5)) is None
    order = []
    while (j := claim(conn, at(4))) is not None:
        order.append(j["id"])
        outcome(conn, j, "ok", at(4))
    assert order == [2, 3, 1]


def test_outage_backoff_and_retry_after(store, conn):
    photo(store, [b"a"])
    for n, minutes in enumerate([1, 2, 4, 8, 16, 32, 60, 60]):
        j = claim(conn, at(1000 * n))
        with transaction(conn):
            pause(conn, j["id"], "outage", at(1000 * n))
        until = conn.execute("SELECT paused_until FROM queue_state").fetchone()[0]
        assert until == at(1000 * n + minutes)
    j = claim(conn, at(9000))
    with transaction(conn):
        pause(conn, j["id"], "outage", at(9000), retry_after=30)
    assert claim(conn, at(9000.4)) is None and claim(conn, at(9000.6)) is not None
    with transaction(conn):
        pause(conn, None, "outage", at(9001), retry_after=86400)  # capped at an hour
    assert conn.execute("SELECT paused_until FROM queue_state").fetchone()[0] == at(
        9061
    )


def test_one_rule_for_charged_failures(store, conn):
    photo(store, [b"a"])
    outcome(conn, claim(conn, at(0)), "invalid", at(1))  # retried at once
    outcome(conn, claim(conn, at(1)), "image", at(2))
    assert job(conn) == ("queued", 2, "image")
    outcome(conn, claim(conn, at(12)), "content", at(13))
    assert job(conn) == ("dead", 3, "content")


def test_a_job_running_at_start_is_charged_as_crashed(store, conn):
    photo(store, [b"a"])
    for n in range(3):
        assert claim(conn, at(20 * n)) is not None  # the call kills the process
        assert recover(conn, at(20 * n + 1)) == 1  # the service starts again
    assert job(conn) == ("dead", 3, "crashed")
    assert claim(conn, at(100)) is None


def test_a_pause_is_announced_once_per_episode(store, conn, monkeypatch):
    photo(store, [b"a"])
    j = claim(conn, at(0))
    with transaction(conn):
        assert pause(conn, j["id"], "outage", at(0)) is True
        assert pause(conn, j["id"], "outage", at(1)) is False
        resume(conn, at(2))
        assert pause(conn, None, "auth", at(3)) is True
        resume(conn, at(4))
        # a budget pause runs out by itself; next morning the spend limit needs Resume
        assert pause(conn, None, "budget", at(20 * 60)) is True
        assert pause(conn, None, "budget", at(20 * 60 + 1)) is False
        assert pause(conn, None, "credit", at(28 * 60 + 5)) is True
        assert pause(conn, None, "credit", at(28 * 60 + 6)) is False
    sent = []
    monkeypatch.setenv("SCRAP_NOTIFY_URL", "http://notify.invalid/topic")
    monkeypatch.setattr(
        spend.urllib.request,
        "urlopen",
        lambda *a, **k: sent.append(a[1]) or io.BytesIO(),
    )
    ingest.notify("credit")
    assert sent == [b"scrap: Claude ingest paused (credit). Open scrap to resume."]


# ---- the worker, with Claude faked

BOARD = {
    "kind": "whiteboard",
    "title": "Queue design",
    "tags": ["Queues", "design", "queues"],
    "description": "A sketch of a job queue",
    "text": "kafka consumer lag\nretry topic",
    "elements": [
        {"type": "rectangle", "id": "a", "x": 10, "y": 10, "width": 100,
         "height": 50, "label": "Queue", "labelFontSize": 20},
        {"type": "arrow", "x": 110, "y": 35, "points": [0, 0, 50, 0],
         "start": "a", "end": "gone"},
        {"type": "ellipse", "id": "far", "x": 5000, "y": 10, "width": 1, "height": 1},
    ],
}  # fmt: skip
USAGE = {"input_tokens": 5000, "output_tokens": 2000}


class Fake:
    """Stands in for claude.complete: each call takes the next result (a dict to
    return as output, or an exception to raise)."""

    def __init__(self, *results):
        self.results, self.calls, self.tickets = list(results), [], []

    def __call__(self, model, system, messages, schema, blob, *, ticket):
        assert isinstance(ticket, spend.Ticket)
        self.calls.append(messages)
        self.tickets.append(ticket)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        content = [{"type": "text", "text": json.dumps(result)}]
        return claude.Completion(result, content, USAGE, model, "end_turn")


def run_one(store, fake):
    return ingest.Worker(store, fake).step()


def test_a_success_stores_the_run_versions_and_page_fields(store, conn):
    ref = photo(store, [jpeg(size=(4032, 3024))])
    fake = Fake(BOARD)
    assert run_one(store, fake) is True
    sent = fake.calls[0][0]["content"][0]
    assert sent["transformations"] == {"oversized_image": "error"}
    run = conn.execute("SELECT * FROM model_run").fetchone()
    assert (run["status"], run["image_width"], run["image_height"]) == (
        "ok",
        2048,
        1536,
    )
    assert run["sent_sha256"] == sent["source"]["sha256"]
    assert store.blob(run["sent_sha256"])[1] == "image/jpeg"
    assert run["cost_microusd"] == 5000 * 4 + 2000 * 20  # $0.06
    assert run["prompt_version"].startswith("photo@")
    request = json.loads(run["request"])
    assert "data" not in json.dumps(request["messages"])  # a blob reference, not base64
    output = json.loads(run["output"])
    assert len(output["elements"]) == 2 and len(output["warnings"]) == 2
    page = store.page(ref["page_id"])
    assert (page["title"], page["kind"], page["rev"]) == (
        "Queue design",
        "whiteboard",
        1,
    )
    assert page["tags"] == ["design", "queues"]
    assert page["slug"] == ref["slug"]  # the slug never changes
    got = page["captures"][0]["blobs"][0]["ingest"]
    assert got["state"] == "done" and got["text"].startswith("kafka")
    assert got["image_kind"] == "whiteboard" and got["drawing"]["version"] == 1
    assert [h["id"] for h in store.search("kafka", 10)] == [ref["page_id"]]
    assert [h["id"] for h in store.search("queue design", 10)] == [ref["page_id"]]
    sha = page["captures"][0]["blobs"][0]["sha256"]
    assert page["body"] == f"![](/api/blobs/{sha}/preview?size=2048)"  # never touched


def test_ingest_leaves_a_body_the_user_rewrote(store, conn):
    ref = photo(store, [jpeg()], text="mine")
    store.update_page(ref["page_id"], 1, None, "all mine now", "me")
    run_one(store, Fake(BOARD))
    page = store.page(ref["page_id"])
    assert (page["body"], page["rev"]) == ("all mine now", 2)


def test_user_fields_win(store, conn):
    ref = photo(store, [jpeg()], text="My board")  # the user gave text: their title
    with transaction(conn):
        conn.execute("UPDATE page SET kind = 'todo', kind_fixed = 1")
        conn.execute("INSERT INTO tag VALUES (?, 'mine')", (ref["page_id"],))
    run_one(store, Fake(BOARD))
    page = store.page(ref["page_id"])
    assert (page["title"], page["kind"], page["tags"]) == ("My board", "todo", ["mine"])


def test_only_the_first_photo_sets_the_title(store, conn):
    ref = photo(store, [jpeg("red"), jpeg("blue")])
    worker = ingest.Worker(store, Fake(BOARD, {**BOARD, "title": "First"}))
    with transaction(conn):  # the second photo is done first
        conn.execute("UPDATE job SET run_after = ? WHERE id = 1", (at(60 * 24 * 365),))
    worker.step()
    assert store.page(ref["page_id"])["title"] != "Queue design"
    with transaction(conn):
        conn.execute("UPDATE job SET run_after = ? WHERE id = 1", (PAST,))
    worker.step()
    assert store.page(ref["page_id"])["title"] == "First"


def test_patch_with_the_title_at_base_rev_keeps_the_model_title(tmp_path):
    client = TestClient(create_app(tmp_path))
    store = Store(tmp_path)
    ref = photo(store, [jpeg()])
    provisional = client.get(f"/api/pages/{ref['page_id']}").json()["title"]
    run_one(store, Fake(BOARD))  # the PWA loaded the page before this finished
    edit = {"base_rev": 1, "title": provisional, "body": "my note"}
    page = client.patch(f"/api/pages/{ref['page_id']}", json=edit).json()
    assert (page["title"], page["rev"], page["slug"]) == (
        "Queue design",
        2,
        ref["slug"],
    )
    edit = {"base_rev": 2, "title": "Mine", "body": "my note"}
    assert (
        client.patch(f"/api/pages/{ref['page_id']}", json=edit).json()["title"]
        == "Mine"
    )


def test_a_user_edit_first_blocks_the_model_title(tmp_path):
    client = TestClient(create_app(tmp_path))
    store = Store(tmp_path)
    ref = photo(store, [jpeg()])
    client.patch(f"/api/pages/{ref['page_id']}", json={"base_rev": 1, "body": "typed"})
    run_one(store, Fake(BOARD))
    assert client.get(f"/api/pages/{ref['page_id']}").json()["title"] != "Queue design"


def test_failures_through_the_worker(store, conn):
    photo(store, [jpeg()])
    no_text = {**BOARD, "text": "", "description": ""}
    fake = Fake(claude.CallError("timeout", "slow"), no_text, no_text)
    worker = ingest.Worker(store, fake)
    worker.step()
    assert job(conn) == ("queued", 1, "timeout")
    conn.execute("UPDATE job SET run_after = ?", (PAST,))
    worker.step()
    assert job(conn) == ("queued", 2, "invalid")  # retried at once
    worker.step()
    assert job(conn) == ("dead", 3, "invalid")
    runs = conn.execute("SELECT status, error_class FROM model_run").fetchall()
    assert [tuple(r) for r in runs] == [
        ("error", "timeout"), ("invalid", "invalid"), ("invalid", "invalid")
    ]  # fmt: skip


def test_a_bad_element_costs_only_itself(store, conn):
    ref = photo(store, [jpeg()])
    off_frame = {"type": "text", "id": "z", "x": -9999, "y": 0, "text": "x"}
    run_one(store, Fake({**BOARD, "elements": [off_frame]}))
    assert job(conn) == ("done", 0, "")
    got = store.page(ref["page_id"])["captures"][0]["blobs"][0]["ingest"]
    assert got["text"].startswith("kafka") and got["drawing"] is None
    output = json.loads(conn.execute("SELECT output FROM model_run").fetchone()[0])
    assert output["warnings"] == ["element 0 dropped: position outside the image"]


def test_a_pause_through_the_worker_refunds_and_a_success_clears_it(store, conn):
    photo(store, [jpeg()])
    worker = ingest.Worker(store, Fake(claude.CallError("credit", "no money"), BOARD))
    worker.step()
    assert job(conn) == ("queued", 0, "credit")
    assert worker.step() is False  # paused until Resume
    ingest.resume_queue(store)
    assert ingest.status(store)["paused"] is False
    worker.step()
    assert job(conn) == ("done", 0, "")


def test_the_daily_budget_pauses_until_midnight(store, conn, monkeypatch):
    monkeypatch.setenv("SCRAP_BUDGET_DAY_USD", "0.05")
    photo(store, [jpeg()])
    photo(store, [jpeg("blue")])
    worker = ingest.Worker(store, Fake(BOARD, BOARD))
    worker.step()  # $0.06 spent
    worker.step()
    assert job(conn, 2) == ("queued", 0, "budget")
    status = ingest.status(store)
    assert status["reason"] == "budget" and status["paused_until"].endswith(
        "T00:00:00.000Z"
    )
    assert status["spent_today_usd"] == 0.06


def test_an_image_that_cannot_be_decoded_is_charged(store, conn):
    photo(store, [b"not an image"])
    run_one(store, Fake())
    assert job(conn) == ("queued", 1, "image")


def test_a_purge_during_the_call_is_harmless(store, conn):
    ref = photo(store, [jpeg()])

    def purge_then_answer(*args, **kwargs):
        with closing(connect(store.db)) as other, transaction(other):
            other.execute("DELETE FROM page WHERE id = ?", (ref["page_id"],))
        return Fake(BOARD)(*args, **kwargs)

    run_one(store, purge_then_answer)
    tables = ("job", "model_run", "derived", "chunk")
    left = [conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables]
    assert left == [0, 0, 0, 0]


def test_reprocess_keeps_a_human_drawing_unless_confirmed(store, conn):
    ref = photo(store, [jpeg()])
    cid, sha = ref["capture_id"], shas(conn, ref["capture_id"])[0]
    run_one(store, Fake(BOARD))
    with transaction(conn):
        scene = {"format": "scene", "elements": []}
        put_derived(
            conn, cid, sha, "excalidraw", "human", at(0), author="me", data=scene
        )
    ingest.reprocess(store, cid, None, False)
    run_one(store, Fake(BOARD))

    def current():
        return conn.execute(
            "SELECT version, producer FROM derived WHERE kind = 'excalidraw'"
            " AND superseded_at IS NULL"
        ).fetchone()

    assert tuple(current()) == (2, "human")  # the model's v3 is history only
    ingest.reprocess(store, cid, sha, True)
    run_one(store, Fake(BOARD))
    assert current()[0] == 4 and current()[1] != "human"


def test_confirming_replace_reaches_a_job_already_queued_or_running(store, conn):
    """Issue #19: Reprocess confirmed while the photo is queued (or running) must
    not lose the confirmation."""
    ref = photo(store, [jpeg()])
    cid, sha = ref["capture_id"], shas(conn, ref["capture_id"])[0]
    run_one(store, Fake(BOARD))
    with transaction(conn):
        put_derived(conn, cid, sha, "excalidraw", "human", at(0), author="me",
                    data={"format": "scene", "elements": []})  # fmt: skip
    assert ingest.reprocess(store, cid, None, False) == {"queued": 1, "already": 0}
    assert ingest.reprocess(store, cid, sha, True) == {"queued": 0, "already": 1}
    run_one(store, Fake(BOARD))
    producer = "SELECT producer FROM derived WHERE kind = 'excalidraw'"
    producer += " AND superseded_at IS NULL"
    assert conn.execute(producer).fetchone()[0] != "human"
    # confirmed while the call runs: the worker reads the options as it finishes
    with transaction(conn):
        put_derived(conn, cid, sha, "excalidraw", "human", at(1), author="me",
                    data={"format": "scene", "elements": []})  # fmt: skip
    ingest.reprocess(store, cid, sha, False)

    def confirm_then_answer(*args, **kwargs):
        assert ingest.reprocess(store, cid, sha, True) == {"queued": 0, "already": 1}
        return Fake(BOARD)(*args, **kwargs)

    run_one(store, confirm_then_answer)
    assert conn.execute(producer).fetchone()[0] != "human"


def test_the_worker_survives_an_exception_and_healthz_reports_its_death(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    app = create_app(tmp_path)
    store = Store(tmp_path)
    worker = app.state.worker
    worker.call = Fake(ValueError("a bug"), BOARD)
    with TestClient(app) as client:
        for colour in ("red", "blue"):
            files = [("file", ("b.jpg", jpeg(colour), "image/jpeg"))]
            client.post("/api/captures", data={"id": new_ulid()}, files=files)
        deadline = time.monotonic() + 10
        while (
            ingest.status(store)["jobs"].get("queued", 0)
            + ingest.status(store)["jobs"].get("running", 0)
            > 1
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        time.sleep(0.2)
        with closing(connect(store.db)) as conn:
            states = [tuple(r) for r in conn.execute(
                "SELECT state, failures, substr(last_error, 1, 8) FROM job ORDER BY id"
            )]  # fmt: skip
        assert states == [("queued", 1, "internal"), ("done", 0, None)]
        assert worker.alive() and client.get("/healthz").status_code == 200
        worker._stop.set()  # the thread ends: as if it had died
        worker.wake()
        worker._thread.join(5)
        response = client.get("/healthz")
        assert response.status_code == 503
        assert response.json()["status"] == "ingest worker stopped"


def test_a_clean_shutdown_gives_the_job_in_flight_back_for_free(tmp_path):
    store = Store(tmp_path)
    store.migrate()
    photo(store, [jpeg()])
    calling, release = threading.Event(), threading.Event()

    def slow(*args, **kwargs):
        calling.set()
        release.wait(10)
        return Fake(BOARD)(*args, **kwargs)

    worker = ingest.Worker(store, slow)
    worker.start()
    assert calling.wait(10)
    worker.stop()
    with closing(connect(store.db)) as conn:
        assert job(conn) == ("queued", 0, "")
        release.set()
        worker._thread.join(5)
        assert job(conn) == ("queued", 0, "")  # the abandoned answer changed nothing
        assert conn.execute("SELECT count(*) FROM derived").fetchone()[0] == 0


# ---- versions, search, trash and purge


def test_versions_search_and_purge(store, conn):
    ref = photo(store, [b"a"], text="whiteboard about queues")
    cid, pid, sha = ref["capture_id"], ref["page_id"], shas(conn, ref["capture_id"])[0]

    def put(kind, **kw):
        with transaction(conn):
            return put_derived(
                conn, cid, sha, kind, kw.pop("producer", "m"), at(0), **kw
            )

    def search(q):
        return [h["id"] for h in store.search(q, 10)]

    def current(kind):
        return conn.execute(
            "SELECT id, version, producer FROM derived WHERE kind = ?"
            " AND superseded_at IS NULL",
            (kind,),
        ).fetchall()

    put("ocr", text="kafka consumer lag\nretry topic")
    put("description", text="A sketch of a message broker")
    d1 = put("excalidraw", data={"format": "skeleton", "elements": []})
    assert search("kafka") == search("broker") == search("whiteboard") == [pid]
    assert search("queues kafka") == [pid]  # words from two parts of the page
    assert search("queues nothere") == []
    assert len(store.search("a", 10)) == 1  # many chunks hit: the page once
    put("ocr", text="kafka consumer lag\nretry stream")
    assert [r["version"] for r in current("ocr")] == [2]
    assert search("topic") == [] and search("stream") == [pid]
    put("excalidraw", producer="human", author="me", text="lag (edited)",
        data={"format": "scene", "elements": []})  # fmt: skip
    assert search("edited") == [pid]
    restored = put("excalidraw", data={"format": "skeleton", "elements": []})  # Restore
    assert current("excalidraw")[0]["id"] == restored["id"] and search("edited") == []
    for sql, message in [
        ("UPDATE derived SET text = 'x' WHERE id = ?", "immutable"),
        ("UPDATE derived SET superseded_at = NULL WHERE id = ?", "stays superseded"),
    ]:
        with pytest.raises(sqlite3.IntegrityError, match=message):
            conn.execute(sql, (d1["id"],))
    # a page edit re-indexes the page's own chunk only
    store.update_page(pid, 1, "renamed page", None, "me")
    assert search("kafka") == search("renamed") == [pid]
    store.delete_page(pid)
    assert search("kafka") == []
    store.delete_page(pid, undo=True)
    assert search("kafka") == [pid]
    conn.execute(
        "INSERT INTO model_run (capture_id, source_sha256, purpose, model,"
        " prompt_version, request, started_at) VALUES (?, ?, 'ingest', 'm', 'p', '{}',"
        " ?)",
        (cid, sha, at(0)),
    )
    conn.execute(
        "INSERT INTO model_run (capture_id, source_sha256, parent_id, purpose, model,"
        " prompt_version, request, started_at) VALUES (?, ?, 1, 'discuss', 'm', 'p',"
        " '{}', ?)",
        (cid, sha, at(0)),
    )
    with transaction(conn):
        conn.execute("DELETE FROM page WHERE id = ?", (pid,))
    left = [conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("job", "model_run", "derived", "chunk", "tag")]  # fmt: skip
    assert left == [0, 0, 0, 0, 0]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('integrity-check')")


def test_a_run_backing_a_version_cannot_be_deleted(store, conn):
    photo(store, [jpeg()])
    run_one(store, Fake(BOARD))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM model_run")


def test_prompt_version_names_the_prompt_and_schema():
    text, version = claude.prompt()
    assert "Excalidraw" in text
    name, digest = version.split("@")
    assert name == "photo" and len(digest) == 12
    assert Path(claude.__file__).with_name("prompts").joinpath("photo.md").is_file()


def test_search_ignores_symbols_and_caps_long_queries(tmp_path):
    client = TestClient(create_app(tmp_path))
    store = Store(tmp_path)
    for n in range(200):
        text = f"salt and pepper quokka {n}" if n == 0 else f"common words {n}"
        store.capture(store.prepare({"id": new_ulid(), "text": text}, []), [], "me")

    def found(q):
        response = client.get("/api/search", params={"q": q})
        assert response.status_code == 200
        return len(response.json())

    for q in ("salt & pepper", "pepper ?", "quokka -", "pepper pepper salt", "_ salt"):
        assert found(q) == 1, q
    assert found("& ? -") == 0
    assert found("quokka pepp") == 1  # every word is a prefix
    assert found(" ".join(["common"] * 100)) == 20
    words = " ".join(f"w{n}" for n in range(999))
    started = time.monotonic()
    assert found(words) == 0 and found("salt " + words) == 0  # 16 words used
    assert found(f"common words {words}") == 0
    assert time.monotonic() - started < 2


def test_lone_surrogates_from_the_model_never_reach_the_database(tmp_path):
    """JSON can carry half a UTF-16 pair; UTF-8 cannot. The page, its download and
    the export all still work, with U+FFFD in its place."""
    store = Store(tmp_path)
    store.migrate()
    ref = photo(store, [jpeg()])
    bad = "\udc00"
    label = {"type": "text", "id": "t", "x": 1, "y": 1, "text": f"label {bad}"}
    answer: dict[str, Any] = dict(BOARD, title=f"Board {bad}", elements=[label],
                                  description=f"About {bad}", text=f"line {bad}",
                                  tags=[f"t{bad}"])  # fmt: skip
    assert run_one(store, Fake(answer))
    with closing(connect(store.db)) as conn:
        assert job(conn) == ("done", 0, "")
        texts = [
            r[0]
            for r in conn.execute("SELECT text FROM derived WHERE text IS NOT NULL")
        ]
    assert sorted(texts) == ["About �", "line �"]
    client = TestClient(create_app(tmp_path))
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert page["title"] == "Board �" and page["tags"] == ["t�"]
    assert client.get(f"/api/pages/{ref['page_id']}/download").status_code == 200
    from scrap.backup import export

    assert export(store, tmp_path / "out") == 1
