# pyright: reportOptionalSubscript=false
"""The spend ledger, the monthly cap and its notices (Claude faked: never called)."""

import io
import json
import threading
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from scrap import claude, ingest, spend
from scrap.app import create_app
from scrap.store import Store, connect, migrations, now, transaction
from test_ingest import BOARD, USAGE, Fake, job, jpeg, photo

OPUS = "claude-opus-5-5"
SETTINGS = (
    "SCRAP_MONTHLY_CAP_USD",
    "SCRAP_BUDGET_DAY_USD",
    "SCRAP_CALL_CAP_USD",
    "SCRAP_PRICES",
    "SCRAP_NOTIFY_URL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    return store


@pytest.fixture
def conn(store):
    with closing(connect(store.db)) as conn:
        yield conn


@pytest.fixture
def sent(monkeypatch):
    """The notices POSTed to SCRAP_NOTIFY_URL."""
    out: list[str] = []
    monkeypatch.setenv("SCRAP_NOTIFY_URL", "http://notify.invalid/topic")
    monkeypatch.setattr(
        spend.urllib.request,
        "urlopen",
        lambda *a, **k: out.append(a[1].decode()) or io.BytesIO(),
    )
    return out


def admit(conn, stamp, attempt="a", input_tokens=1000, max_tokens=1000, **kw):
    with transaction(conn):
        return spend.admit(conn, attempt=attempt, purpose="ingest", model=OPUS,
                           input_tokens=input_tokens, max_tokens=max_tokens,
                           stamp=stamp, **kw)  # fmt: skip


def settle(conn, stamp, attempt="a", usage=None, **kw):
    with transaction(conn):
        return spend.settle(conn, attempt, stamp, usage=usage, **kw)


def ledger(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM spend ORDER BY id")]


# ---- cost


def test_cost_from_usage_and_the_price_table(monkeypatch):
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000,
             "cache_creation_input_tokens": 1_000_000,
             "cache_read_input_tokens": 1_000_000}  # fmt: skip
    assert (
        spend.cost_microusd(OPUS, usage) == 4_000_000 + 2_000_000 + 5_000_000 + 200_000
    )
    assert spend.cost_microusd(OPUS, {"input_tokens": 1}) == 4  # rounded up, never down
    unknown = spend.cost_microusd("claude-unknown", usage)
    assert unknown == 10_000_000 + 5_000_000 + 12_500_000 + 250_000  # the dearest
    monkeypatch.setenv("SCRAP_PRICES", '{"claude-unknown": [1, 2, 3, 4]}')
    assert spend.cost_microusd("claude-unknown", {"output_tokens": 10}) == 20
    assert spend.cost_microusd(OPUS, {"output_tokens": 10}) == 200  # still there


@pytest.mark.parametrize(
    "name, value",
    [
        ("SCRAP_PRICES", "not json"),
        ("SCRAP_PRICES", '{"m": [1, 2, 3]}'),
        ("SCRAP_PRICES", '{"m": [1, 2, 3, -4]}'),
        ("SCRAP_PRICES", "[1]"),
        ("SCRAP_MONTHLY_CAP_USD", "lots"),
        ("SCRAP_MONTHLY_CAP_USD", "-1"),
        ("SCRAP_CALL_CAP_USD", "nan"),
        ("SCRAP_BUDGET_DAY_USD", "inf"),
    ],
)
def test_a_bad_setting_stops_the_start(store, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit, match=name):
        ingest.Worker(store, Fake())


def test_an_unknown_model_is_costed_dearest_and_flagged(conn):
    admit(conn, "2099-01-01T00:00:00.000Z")
    settle(conn, "2099-01-01T00:00:01.000Z", model="claude-new", usage=USAGE)
    row = ledger(conn)[0]
    assert (row["model"], row["flag"]) == ("claude-new", "unpriced")
    assert row["cost_microusd"] == 5000 * 10 + 2000 * 50
    assert (row["input_tokens"], row["output_tokens"]) == (5000, 2000)


# ---- the cap


def test_the_cap_is_checked_before_the_call_with_the_worst_case(conn, monkeypatch):
    worst = spend.worst_case(OPUS, 1000, 1000)
    assert worst == 1000 * 5 + 1000 * 20  # input at the dearer of input and cache write
    monkeypatch.setenv("SCRAP_MONTHLY_CAP_USD", str(2.5 * worst / 1e6))
    stamp = "2099-01-10T00:00:00.000Z"
    admit(conn, stamp, "a")
    admit(conn, stamp, "b")  # two in flight: each holds its worst case
    with pytest.raises(spend.RefusedError) as refused:
        admit(conn, stamp, "c")
    assert refused.value.reason == "cap"
    settle(conn, stamp, "a", usage={"input_tokens": 10})  # a cost far less
    admit(conn, stamp, "c")
    assert [r["attempt"] for r in ledger(conn)] == ["a", "b", "c"]


def test_no_cap_and_no_budget(conn, monkeypatch):
    monkeypatch.setenv("SCRAP_MONTHLY_CAP_USD", "0")
    monkeypatch.setenv("SCRAP_BUDGET_DAY_USD", "0")
    for n in range(5):
        admit(conn, "2099-01-01T00:00:00.000Z", str(n), max_tokens=10**7)
    assert spend.due(conn, "2099-01-01T00:00:00.000Z") == []
    assert spend.summary(conn, "2099-01-01T00:00:00.000Z")["monthly_cap_usd"] is None


def test_admit_needs_a_transaction(conn):
    with pytest.raises(RuntimeError):
        spend.admit(conn, attempt="a", purpose="ingest", model=OPUS, input_tokens=1,
                    max_tokens=1, stamp=now())  # fmt: skip


def test_the_worker_stops_at_the_cap_and_photos_stay_queued(store, conn, monkeypatch):
    photo(store, [jpeg()])
    second = photo(store, [jpeg("blue")])
    fake = Fake(BOARD, BOARD)
    ingest.Worker(store, fake).step()
    worst = fake.tickets[0].estimate
    # a cap that held one call's worst case, now spent past by its real cost
    monkeypatch.setenv("SCRAP_MONTHLY_CAP_USD", str((worst + 30_000) / 1e6))
    worker = ingest.Worker(store, fake)
    assert worker.step() is True
    assert len(fake.calls) == 1  # refused before calling
    assert job(conn, 2) == ("queued", 0, "cap")
    status = ingest.status(store)
    assert (status["paused"], status["reason"]) == (True, "cap")
    assert status["paused_until"] == spend.next_month(now())
    assert status["spent_month_usd"] == 0.06 and status["capped"] is False
    blob = store.page(second["page_id"])["captures"][0]["blobs"][0]
    assert blob["ingest"]["state"] == "paused"
    assert worker.step() is False  # nothing claimed while capped
    assert conn.execute("SELECT count(*) FROM model_run").fetchone()[0] == 1


def test_a_per_call_ceiling_lowers_max_tokens_or_refuses(store, conn, monkeypatch):
    photo(store, [jpeg()])
    monkeypatch.setenv("SCRAP_CALL_CAP_USD", "0.10")
    fake = Fake(BOARD)
    ingest.Worker(store, fake).step()
    ticket = fake.tickets[0]
    assert 1024 <= ticket.max_tokens < claude.MAX_TOKENS
    assert ticket.estimate <= 100_000
    request = json.loads(conn.execute("SELECT request FROM model_run").fetchone()[0])
    assert request["max_tokens"] == ticket.max_tokens
    photo(store, [jpeg("blue")])
    monkeypatch.setenv("SCRAP_CALL_CAP_USD", "0.01")  # not even the input fits
    ingest.Worker(store, fake).step()
    assert len(fake.calls) == 1
    assert job(conn, 2) == ("queued", 1, "ceiling")


# ---- the ledger


def test_a_retry_is_counted_once_per_attempt(conn):
    stamp = "2099-01-01T00:00:00.000Z"
    first = admit(conn, stamp, "a")
    assert admit(conn, stamp, "a") == first  # the same attempt reserves nothing more
    settle(conn, stamp, "a", usage=USAGE)
    settle(conn, stamp, "a", usage={"input_tokens": 10**9})  # a second settle: no-op
    assert spend.spent(conn, stamp) == 5000 * 4 + 2000 * 20
    admit(conn, stamp, "b")  # the job's retry is a new call
    settle(conn, stamp, "b", usage=USAGE)
    assert spend.spent(conn, stamp) == 2 * (5000 * 4 + 2000 * 20)


def test_the_ledger_is_append_only(conn):
    admit(conn, now())
    settle(conn, now(), usage=USAGE)
    with pytest.raises(Exception, match="append-only"):
        conn.execute("DELETE FROM spend")
    with pytest.raises(Exception, match="never changes"):
        conn.execute("UPDATE spend SET cost_microusd = 0")


def test_retried_jobs_through_the_worker(store, conn):
    photo(store, [jpeg()])
    fake = Fake(claude.CallError("timeout", "slow"),
                claude.CallError("outage", "529"), BOARD)  # fmt: skip
    worker = ingest.Worker(store, fake)
    worker.step()  # a timeout may have been billed: its worst case, flagged
    conn.execute("UPDATE job SET run_after = '2000-01-01T00:00:00.000Z'")
    worker.step()  # an outage was not
    ingest.resume_queue(store)
    worker.step()
    rows = ledger(conn)
    assert [(r["state"], r["flag"]) for r in rows] == [
        ("settled", "estimated"), ("settled", None), ("settled", None)
    ]  # fmt: skip
    assert rows[0]["cost_microusd"] == fake.tickets[0].estimate
    assert rows[1]["cost_microusd"] == 0
    assert rows[2]["cost_microusd"] == 60_000
    assert len({r["attempt"] for r in rows}) == 3
    assert [r["run_id"] for r in rows] == [1, 2, 3]


def test_a_purge_never_lowers_the_spend(store, conn):
    ref = photo(store, [jpeg()])
    ingest.Worker(store, Fake(BOARD)).step()
    with transaction(conn):
        conn.execute("DELETE FROM page WHERE id = ?", (ref["page_id"],))
    assert conn.execute("SELECT count(*) FROM model_run").fetchone()[0] == 0
    assert ingest.status(store)["spent_today_usd"] == 0.06


def test_a_failure_recording_the_result_keeps_its_cost(store, conn, monkeypatch):
    photo(store, [jpeg()])
    worker = ingest.Worker(store, Fake(BOARD))

    def broken(*args):
        raise RuntimeError("a bug")

    monkeypatch.setattr(worker, "_page_fields", broken)
    worker.step()
    assert job(conn) == ("queued", 1, "internal")
    row = ledger(conn)[0]
    assert (row["state"], row["cost_microusd"], row["flag"]) == (
        "settled",
        60_000,
        None,
    )


def test_a_call_in_flight_at_a_crash_counts_its_worst_case(store, conn):
    photo(store, [jpeg()])
    worker = ingest.Worker(store, Fake())

    def crash(*args, **kwargs):
        raise SystemExit  # the process dies mid-call: nothing is recorded

    worker.call = crash
    with pytest.raises(SystemExit):
        worker.step()
    row = ledger(conn)[0]
    assert row["state"] == "reserved"
    with closing(connect(store.db)) as other:
        ingest.recover(other, now())  # the next start
    row = ledger(conn)[0]
    assert (row["state"], row["flag"]) == ("settled", "estimated")
    assert row["cost_microusd"] == row["estimate_microusd"] > 0


def test_concurrent_callers_never_overrun_the_cap(store, monkeypatch):
    worst = spend.worst_case(OPUS, 1000, 1000)
    monkeypatch.setenv("SCRAP_MONTHLY_CAP_USD", str(5 * worst / 1e6))
    stamp = now()
    admitted, refused = [], []
    start = threading.Barrier(12)

    def caller(n):
        with closing(connect(store.db)) as conn:
            start.wait()
            try:
                admit(conn, stamp, f"call-{n}")
                admitted.append(n)
            except spend.RefusedError:
                refused.append(n)

    threads = [threading.Thread(target=caller, args=(n,)) for n in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert (len(admitted), len(refused)) == (5, 7)
    with closing(connect(store.db)) as conn:
        assert spend.spent(conn, spend.month_start(stamp)) == 5 * worst


# ---- months (UTC)


def test_month_rollover():
    assert spend.next_month("2099-01-31T23:59:59.999Z") == "2099-02-01T00:00:00.000Z"
    assert spend.next_month("2099-12-15T00:00:00.000Z") == "2100-01-01T00:00:00.000Z"
    assert spend.month_start("2099-03-31T23:00:00.000Z") == "2099-03-01T00:00:00.000Z"


def test_a_new_month_starts_from_nothing(conn, monkeypatch):
    worst = spend.worst_case(OPUS, 1000, 1000)
    monkeypatch.setenv("SCRAP_MONTHLY_CAP_USD", str(worst / 1e6))
    admit(conn, "2099-01-31T23:59:59.000Z", "jan")
    with pytest.raises(spend.RefusedError):
        admit(conn, "2099-01-31T23:59:59.999Z", "jan-2")
    admit(conn, "2099-02-01T00:00:00.000Z", "feb")  # a UTC month later
    assert spend.spent(conn, "2099-02-01T00:00:00.000Z") == worst
    with transaction(conn):
        assert ingest.pause(conn, None, "cap", "2099-01-31T23:59:59.999Z") is True
    until = conn.execute("SELECT paused_until FROM queue_state").fetchone()[0]
    assert until == "2099-02-01T00:00:00.000Z"
    assert ingest.claim(conn, "2099-02-01T00:00:00.000Z") is None  # nothing queued


# ---- notices


def test_the_80_percent_and_cap_notices_go_once_a_month(store, sent, monkeypatch):
    monkeypatch.setenv("SCRAP_MONTHLY_CAP_USD", "1")
    jan = "2099-01-05T00:00:00.000Z"
    with closing(connect(store.db)) as conn:
        admit(conn, jan, "a", max_tokens=10_000)
        levels = settle(conn, jan, "a", usage={"output_tokens": 40_000})  # $0.80
    assert levels == ["warn"]
    spend.notify(levels)
    assert sent == ["scrap: Claude spend this month passed 80% of the $1.00 cap."]
    with closing(connect(store.db)) as conn:  # a restart: the notice was kept
        admit(conn, jan, "b", max_tokens=1000)
        assert settle(conn, jan, "b", usage={"output_tokens": 1}) == []
        with pytest.raises(spend.RefusedError):
            admit(conn, jan, "c", max_tokens=10_000)
        with transaction(conn):
            assert spend.due(conn, jan, capped=True) == ["cap"]
            assert spend.due(conn, jan, capped=True) == []
        feb = "2099-02-01T00:00:00.000Z"
        admit(conn, feb, "d", max_tokens=10_000)
        assert settle(conn, feb, "d", usage={"output_tokens": 50_000}) == [
            "warn", "cap"
        ]  # fmt: skip
        months = conn.execute("SELECT month, level FROM spend_notice ORDER BY 1, 2")
        assert [tuple(r) for r in months] == [
            ("2099-01", "cap"), ("2099-01", "warn"),
            ("2099-02", "cap"), ("2099-02", "warn"),
        ]  # fmt: skip


def test_the_worker_announces_the_cap_once(store, conn, sent, monkeypatch):
    photo(store, [jpeg()])
    monkeypatch.setenv("SCRAP_MONTHLY_CAP_USD", "0.01")  # below one call's worst case
    worker = ingest.Worker(store, Fake())
    worker.step()
    assert job(conn) == ("queued", 0, "cap")
    assert len(sent) == 1 and "reached the $0.01 cap" in sent[0]
    ingest.resume_queue(store)  # Resume while still capped: paused again, no new notice
    worker.step()
    restarted = ingest.Worker(store, Fake())
    ingest.resume_queue(store)
    restarted.step()
    assert len(sent) == 1 and job(conn) == ("queued", 0, "cap")


def test_notices_carry_no_secrets(sent, monkeypatch):
    monkeypatch.setenv("SCRAP_MONTHLY_CAP_USD", "20")
    spend.notify(["warn", "cap"])
    assert all("notify.invalid" not in m and "sk-" not in m for m in sent)


# ---- reading it


def test_get_api_ingest_has_the_spend(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_MONTHLY_CAP_USD", "20")
    client = TestClient(create_app(tmp_path))
    store = Store(tmp_path)
    photo(store, [jpeg()])
    ingest.Worker(store, Fake(BOARD)).step()
    got = client.get("/api/ingest").json()
    assert got["spent_today_usd"] == got["spent_month_usd"] == 0.06
    assert (got["monthly_cap_usd"], got["budget_day_usd"], got["capped"]) == (
        20, 3, False
    )  # fmt: skip
    assert "ANTHROPIC" not in json.dumps(got)


def test_scrap_spend_prints_the_month(tmp_path, capsys, monkeypatch):
    from scrap.__main__ import main

    store = Store(tmp_path)
    store.migrate()
    with closing(connect(store.db)) as conn:
        admit(conn, "2099-03-01T10:00:00.000Z", "a")
        settle(conn, "2099-03-01T10:00:00.000Z", "a", usage=USAGE)
        admit(conn, "2099-03-02T10:00:00.000Z", "b")
        settle(conn, "2099-03-02T10:00:00.000Z", "b", model="claude-x", usage=USAGE)
        admit(conn, "2099-04-01T00:00:00.000Z", "c")  # another month
    main(["spend", "--data-dir", str(tmp_path), "--month", "2099-03"])
    out = capsys.readouterr().out
    assert "2099-03-01  claude-opus-5-5" in out and "$  0.0600" in out
    assert "2099-03-02  claude-x" in out and "(1 estimated or unpriced)" in out
    assert "claude-opus-5-5: $0.0600" in out and "claude-x: $0.1500" in out
    assert "total: $0.2100 of the $20.00 cap (1%), 2 calls" in out
    with pytest.raises(SystemExit):
        main(["spend", "--data-dir", str(tmp_path), "--month", "2099-13"])
    with pytest.raises(SystemExit, match="no database"):
        main(["spend", "--data-dir", str(tmp_path / "none")])


# ---- migration


def test_0004_copies_recorded_runs_into_the_ledger(tmp_path):
    db = tmp_path / "scrap.db"
    with closing(connect(db)) as conn:
        script = "".join(migrations()[:3])
        conn.executescript(f"BEGIN; {script} PRAGMA user_version = 3; COMMIT;")
        conn.executescript("""
            INSERT INTO page (id, slug, title, created_at, updated_at)
                VALUES ('P', 'p', 't', 'x', 'x');
            INSERT INTO capture (id, kind, source, author, created_at, received_at,
                page_id) VALUES ('C', 'photo', 'pwa', 'me', 'x', 'x', 'P');
            INSERT INTO model_run (capture_id, source_sha256, purpose, model,
                served_model, prompt_version, request, usage, cost_microusd, status,
                started_at, finished_at)
            VALUES ('C', 's', 'ingest', 'claude-opus-5-5', 'claude-opus-5-5', 'p@1',
                '{}', '{"input_tokens": 5000, "output_tokens": 2000}', 60000, 'ok',
                '2099-01-01T00:00:00.000Z', '2099-01-01T00:00:30.000Z'),
                   ('C', 's', 'ingest', 'claude-opus-5-5', NULL, 'p@1', '{}', NULL, 0,
                'error', '2099-01-01T00:01:00.000Z', NULL);
            UPDATE queue_state SET reason = 'budget',
                paused_until = '2099-01-02T00:00:00.000Z';
        """)
    Store(tmp_path).migrate()
    with closing(connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
        rows = ledger(conn)
        assert len(rows) == 1
        assert (rows[0]["attempt"], rows[0]["cost_microusd"], rows[0]["state"]) == (
            "run:1", 60000, "settled"
        )  # fmt: skip
        assert rows[0]["output_tokens"] == 2000
        q = conn.execute("SELECT reason, paused_until FROM queue_state").fetchone()
        assert tuple(q) == ("budget", "2099-01-02T00:00:00.000Z")
        conn.execute("UPDATE queue_state SET reason = 'cap'")  # the new reason
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
