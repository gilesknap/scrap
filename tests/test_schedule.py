"""scrap schedule and its cron matcher (ADR 46)."""

import json
import sys
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from scrap import schedule
from scrap.__main__ import main
from scrap.cron import Cron
from scrap.replica import heartbeat_age_hours
from scrap.schedule import Job, Scheduler, load
from scrap.store import Store


def at(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


@pytest.mark.parametrize(
    "cron,when,hit",
    [
        ("30 4 * * *", "2026-11-05 04:30", True),
        ("30 4 * * *", "2026-11-05 04:31", False),
        ("11 4 * * 0", "2026-11-08 04:11", True),  # a Sunday
        ("11 4 * * 7", "2026-11-08 04:11", True),
        ("11 4 * * 0", "2026-11-09 04:11", False),
        ("11 4 * * sun", "2026-11-08 04:11", True),
        ("50 3 1 * *", "2026-12-01 03:50", True),
        ("50 3 1 * *", "2026-12-02 03:50", False),
        ("*/15 * * * *", "2026-11-05 10:45", True),
        ("*/15 * * * *", "2026-11-05 10:46", False),
        ("0 9-17 * * mon-fri", "2026-11-06 12:00", True),
        ("0 9-17 * * mon-fri", "2026-11-07 12:00", False),
        ("0 0 1 jan *", "2027-01-01 00:00", True),
        ("0,30 1 * * *", "2026-11-05 01:30", True),
        ("@daily", "2026-11-05 00:00", True),
        ("@hourly", "2026-11-05 07:00", True),
        ("5/10 * * * *", "2026-11-05 07:15", True),
        # Both day fields set: either, as cron has it
        ("0 0 13 * fri", "2026-11-13 00:00", True),
        ("0 0 13 * fri", "2026-11-06 00:00", True),
        ("0 0 13 * fri", "2026-11-07 00:00", False),
    ],
)
def test_cron(cron, when, hit):
    assert Cron(cron).matches(at(when)) is hit


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "* * * *",
        "61 * * * *",
        "* 24 * * *",
        "a b c d e",
        "*/0 * * * *",
        "5-1 * * * *",
    ],
)
def test_cron_refuses(bad):
    with pytest.raises(ValueError):
        Cron(bad)


def job(name="j", cron="* * * * *", command=None, timeout=30.0, zone=None):
    return Job(name, Cron(cron), zone, timeout, command or ["true"])


def test_load_leaves_out_a_bad_schedule_and_keeps_the_rest(caplog):
    text = json.dumps(
        [
            {"name": "bad", "schedule": "nope", "timeoutSeconds": 1, "command": ["x"]},
            {"name": "zone", "schedule": "* * * * *", "timeZone": "No/Where",
             "timeoutSeconds": 1, "command": ["x"]},
            {"name": "ok", "schedule": "30 4 * * *", "timeZone": "Europe/London",
             "timeoutSeconds": 5, "command": ["x"]},
        ]
    )  # fmt: skip
    jobs = load(text)
    assert [j.name for j in jobs] == ["ok"]
    assert "job bad will not run" in caplog.text
    assert "job zone will not run" in caplog.text


def test_a_job_follows_its_time_zone():
    jobs = load(json.dumps([{"name": "z", "schedule": "30 4 * * *",
                             "timeZone": "Asia/Tokyo", "timeoutSeconds": 1,
                             "command": ["true"]}]))  # fmt: skip
    assert jobs[0].due(at("2026-11-04 19:30"))
    assert not jobs[0].due(at("2026-11-05 04:30"))


def test_a_job_runs_and_reports(caplog):
    caplog.set_level("INFO")
    assert Scheduler([]).run_job(job()) == 0
    assert "job j: done" in caplog.text


def test_a_failing_job_is_reported_and_notified_not_raised(monkeypatch, caplog):
    said = []
    monkeypatch.setattr(schedule, "notify", said.append)
    assert Scheduler([]).run_job(job(command=["false"])) == 1
    assert "job j: failed, exit 1" in caplog.text
    assert said == ["scrap: scheduled job j failed"]


def test_a_job_past_its_deadline_is_stopped(monkeypatch, caplog):
    monkeypatch.setattr(schedule, "notify", lambda m: None)
    code = Scheduler([]).run_job(job(command=["sleep", "30"], timeout=0.2))
    assert code != 0
    assert "deadline" in caplog.text


def test_tick_starts_what_is_due_and_nothing_else(tmp_path):
    out = tmp_path / "ran"
    jobs = [
        job("yes", "30 4 * * *", ["touch", str(out)]),
        job("no", "31 4 * * *", ["touch", str(tmp_path / "wrong")]),
    ]
    sched = Scheduler(jobs)
    sched.tick(at("2026-11-05 04:30"))
    for thread in sched.threads:
        thread.join(5)
    assert out.exists() and not (tmp_path / "wrong").exists()


def test_a_job_still_running_is_not_started_again(tmp_path, caplog):
    sched = Scheduler([job("slow", command=["sleep", "30"])])
    sched.tick(at("2026-11-05 04:30"))
    for _ in range(100):
        if "slow" in sched.running:
            break
        time.sleep(0.05)
    sched.tick(at("2026-11-05 04:31"))
    assert len(sched.threads) == 1
    assert "still running" in caplog.text
    sched.stopping.set()
    schedule._stop(sched.running["slow"])
    sched.threads[0].join(5)


def test_stopping_stops_a_job_and_the_loop(tmp_path):
    sched = Scheduler([job("slow", command=["sleep", "30"])])
    runner = threading.Thread(target=sched.run)
    runner.start()
    for _ in range(100):
        if "slow" in sched.running:
            break
        time.sleep(0.05)
    assert "slow" in sched.running
    start = time.monotonic()
    sched.stop()
    runner.join(15)
    assert not runner.is_alive()
    assert time.monotonic() - start < 10


def test_it_stamps_the_database_at_most_every_so_often(tmp_path, monkeypatch):
    store = Store(tmp_path, tmp_path / "s.db")
    store.migrate()
    calls = []
    monkeypatch.setattr(schedule, "beat", calls.append)
    sched = Scheduler([], store.db)
    start = at("2026-11-05 04:00")
    for minute in range(31):
        sched.tick(start + timedelta(minutes=minute))
    assert len(calls) == 3  # 0, 15 and 30 minutes


def test_the_stamp_reaches_the_database(tmp_path):
    store = Store(tmp_path, tmp_path / "s.db")
    store.migrate()
    Scheduler([], store.db).tick(datetime.now(UTC))
    age = heartbeat_age_hours(store.db)
    assert age is not None and age < 0.1


def test_a_failed_stamp_does_not_stop_it(tmp_path, monkeypatch, caplog):
    def broken(db):
        raise OSError("locked")

    monkeypatch.setattr(schedule, "beat", broken)
    Scheduler([], tmp_path / "s.db").tick(at("2026-11-05 04:00"))
    assert "could not stamp" in caplog.text


def text(*jobs):
    return json.dumps(
        [{"name": n, "schedule": "0 0 1 1 *", "timeoutSeconds": 30,
          "command": c} for n, c in jobs]
    )  # fmt: skip


def test_run_a_job_now_with_its_exit_status(tmp_path, monkeypatch):
    out = tmp_path / "ran"
    monkeypatch.delenv("SCRAP_DB_PATH", raising=False)
    monkeypatch.setenv(
        "SCRAP_SCHEDULE",
        text(("a", ["touch", str(out)]), ("b", [sys.executable, "-c", "exit(3)"])),
    )
    main(["schedule", "--run", "a"])
    assert out.exists()
    with pytest.raises(SystemExit) as stopped:
        main(["schedule", "--run", "b"])
    assert stopped.value.code == 3
    with pytest.raises(SystemExit, match="no job c"):
        main(["schedule", "--run", "c"])
