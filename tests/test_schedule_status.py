"""scrap schedule's records of its jobs, scrap schedule status, the metrics (#558)."""

import json
import os
import socket
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrap import metrics, schedule_record, schedule_status
from scrap.__main__ import main
from scrap.cron import Cron
from scrap.schedule import Job, Scheduler
from scrap.schedule_record import held, lock_path, read
from scrap.schedule_status import Backup, collect, newest_backup, text
from scrap.store import Store


@pytest.fixture(autouse=True)
def private_locks(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    monkeypatch.setattr(schedule_record, "_failing", set())


@pytest.fixture
def db(tmp_path):
    store = Store(tmp_path, tmp_path / "s.db")
    store.migrate()
    return store.db


def at(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def job(name="j", cron="30 4 * * *", command=None, timeout=30.0, **kw):
    return Job(name, Cron(cron), None, timeout, command or ["true"], **kw)


def put(db, name, **fields):
    """A record as if written at the times given."""
    fields.setdefault("seen_at", "2026-01-01T00:00:00.000Z")
    names = ", ".join(["name", *fields])
    marks = ", ".join("?" * (len(fields) + 1))
    with sqlite3.connect(db) as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO scheduled_job ({names}) VALUES ({marks})",
            (name, *fields.values()),
        )


# The cron's times, forward and back


def test_times_after_and_before():
    cron = Cron("30 4 * * *")
    assert next(cron.times(at("2026-11-05 04:30"))) == at("2026-11-06 04:30")
    back = cron.times(at("2026-11-05 04:30"), back=True)
    assert [next(back), next(back)] == [at("2026-11-05 04:30"), at("2026-11-04 04:30")]


def test_times_in_a_zone_are_utc():
    cron = Cron("30 4 * * *")
    tokyo = next(cron.times(at("2026-11-05 00:00"), ZoneInfo("Asia/Tokyo")))
    assert tokyo == at("2026-11-05 19:30")


def test_times_agree_with_matches_across_a_dst_change():
    london = ZoneInfo("Europe/London")
    cron = Cron("*/20 1 * * *")
    start = at("2026-10-24 23:00")
    walked = [
        start + timedelta(minutes=i)
        for i in range(1, 300)
        if cron.matches((start + timedelta(minutes=i)).astimezone(london))
    ]
    found = []
    for t in cron.times(start, london):
        if t > walked[-1]:
            break
        found.append(t)
    assert found == walked and len(walked) == 6  # 01:00-01:40 twice


def test_a_schedule_that_never_fires_has_no_times():
    started = time.monotonic()
    assert list(Cron("0 0 30 2 *").times(at("2026-11-05 00:00"))) == []
    assert time.monotonic() - started < 5


def test_weekly_and_yearly_go_back_far_enough():
    back = Cron("11 4 * * 0").times(at("2026-11-07 12:00"), back=True)
    assert [next(back), next(back)] == [at("2026-11-01 04:11"), at("2026-10-25 04:11")]
    assert next(Cron("0 0 1 1 *").times(at("2026-11-07 12:00"), back=True)) == at(
        "2026-01-01 00:00"
    )


# Recording each result


def script(tmp_path, line, code):
    path = tmp_path / "run.py"
    path.write_text(f"import sys\nprint({line!r}, file=sys.stderr)\nsys.exit({code})\n")
    return [sys.executable, str(path)]


def test_an_ok_run_is_recorded(db):
    assert Scheduler([], db).run_job(job("gc")) == 0
    record = read(db)["gc"]
    assert record.result == "ok" and record.exit_code == 0
    assert record.started_at and record.finished_at and record.ok_at
    assert record.started_at <= record.finished_at == record.ok_at


def test_a_failure_keeps_the_last_success(db, monkeypatch):
    monkeypatch.setattr("scrap.schedule.notify", lambda m: None)
    sched = Scheduler([], db)
    sched.run_job(job("gc"))
    ok_at = read(db)["gc"].ok_at
    assert sched.run_job(job("gc", command=["sh", "-c", "exit 3"])) == 3
    record = read(db)["gc"]
    assert (record.result, record.exit_code, record.ok_at) == ("failed", 3, ok_at)


def test_a_pause_is_recorded_as_paused(db, tmp_path):
    command = script(tmp_path, "stopped: the queue is paused (budget)", 1)
    Scheduler([], db).run_job(job("enrich", command=command, pausable=True))
    record = read(db)["enrich"]
    assert (record.result, record.exit_code, record.ok_at) == ("paused", 1, None)


def test_a_deadline_is_recorded(db, monkeypatch):
    monkeypatch.setattr("scrap.schedule.notify", lambda m: None)
    Scheduler([], db).run_job(job("slow", command=["sleep", "30"], timeout=0.2))
    assert read(db)["slow"].result == "deadline"


def test_one_that_cannot_start_is_recorded(db, monkeypatch):
    monkeypatch.setattr("scrap.schedule.notify", lambda m: None)
    Scheduler([], db).run_job(job("x", command=["/no/such/program"]))
    record = read(db)["x"]
    assert (record.result, record.exit_code) == ("not-started", 127)


def test_stopped_with_the_pod_is_recorded(db):
    sched = Scheduler([], db)
    sched.stopping = True  # as if the pod were stopping when it ended
    sched.run_job(job("j", command=["sh", "-c", "exit 143"]))
    assert read(db)["j"].result == "stopped"


def test_a_run_now_is_recorded(db, monkeypatch):
    monkeypatch.setenv("SCRAP_DB_PATH", str(db))
    monkeypatch.setenv(
        "SCRAP_SCHEDULE",
        json.dumps(
            [
                {
                    "name": "a",
                    "schedule": "0 0 1 1 *",
                    "timeoutSeconds": 30,
                    "command": ["true"],
                }
            ]
        ),
    )
    main(["schedule", "--run", "a"])
    assert read(db)["a"].result == "ok"


def test_a_failure_to_record_never_breaks_the_job(tmp_path, caplog):
    out = tmp_path / "ran"
    no_table = tmp_path / "plain.db"
    sqlite3.connect(no_table).close()
    for where in (no_table, tmp_path / "no" / "such" / "dir.db"):
        out.unlink(missing_ok=True)
        sched = Scheduler([job("j", "* * * * *", ["touch", str(out)])], where)
        assert sched.run_job(sched.jobs[0]) == 0
        assert out.exists()
        sched.tick(at("2026-11-05 04:30"))  # noting the jobs fails too, quietly
        sched.threads[0].join(5)
    assert "could not record" in caplog.text


def test_a_record_failure_is_logged_once_until_it_works(tmp_path, caplog):
    caplog.set_level("INFO")
    db = tmp_path / "s.db"
    sqlite3.connect(db).close()  # below the migration: no table
    sched = Scheduler([job("a")], db)
    for _ in range(5):
        sched.note_jobs()
        sched.run_job(sched.jobs[0])
    failures = [r for r in caplog.records if "could not record" in r.getMessage()]
    # Once for the list of jobs, once for job a (its start and end share it)
    assert len(failures) == 2
    assert all(r.levelname == "WARNING" and not r.exc_info for r in failures)
    Store(tmp_path, db).migrate()
    sched.note_jobs()
    sched.run_job(sched.jobs[0])
    assert "works again" in caplog.text
    assert read(db)["a"].result == "ok"


def test_the_jobs_are_noted_once_the_table_is_there(tmp_path):
    db = tmp_path / "s.db"
    sched = Scheduler([job("a"), job("b")], db)
    sched.note_jobs()
    assert not sched.seen
    Store(tmp_path, db).migrate()
    sched.note_jobs()
    assert sched.seen and set(read(db)) == {"a", "b"}
    first = read(db)["a"].seen_at
    Scheduler([job("a")], db).note_jobs()
    assert read(db)["a"].seen_at == first  # known since the first time


# Running now, from the lock


def test_held_sees_the_jobs_lock(tmp_path):
    from scrap.schedule import _lock

    if not Path("/proc/locks").exists():
        pytest.skip("no /proc/locks here")
    assert held(lock_path("busy")) is False
    lock = _lock("busy")
    assert lock is not None
    assert held(lock_path("busy")) is True
    lock.close()
    assert held(lock_path("busy")) is False


def test_without_proc_locks_running_comes_from_the_records(db, tmp_path, monkeypatch):
    monkeypatch.setattr(schedule_status, "held", lambda path: None)
    put(db, "j", started_at="2026-11-05T04:30:00Z", finished_at="2026-11-04T04:31:00Z")
    report = collect([job("j")], db, None, at("2026-11-05 04:40"))
    assert report.jobs[0].running


def test_a_run_killed_midway_is_interrupted_not_healthy(db, monkeypatch):
    monkeypatch.setattr(schedule_status, "held", lambda path: False)
    put(
        db,
        "gc",
        started_at="2026-11-05T04:30:00Z",
        finished_at="2026-11-04T04:31:00Z",
        result="ok",
        exit_code=0,
        ok_at="2026-11-04T04:31:00Z",
    )
    report = collect([job("gc")], db, None, at("2026-11-05 12:00"))
    status = report.jobs[0]
    assert status.interrupted and not status.running
    assert report.problems == ["job gc: its last run did not finish (killed mid-run)"]
    assert "INTERRUPTED" in text(report)
    assert schedule_status.as_json(report)["jobs"][0]["interrupted"] is True
    assert 'scrap_job_interrupted{job="gc"} 1.0' in metrics.render(report).splitlines()


def test_a_run_going_now_is_not_interrupted(db, monkeypatch):
    monkeypatch.setattr(schedule_status, "held", lambda path: True)
    put(
        db,
        "gc",
        started_at="2026-11-05T04:30:00Z",
        finished_at="2026-11-04T04:31:00Z",
        ok_at="2026-11-04T04:31:00Z",
    )
    report = collect([job("gc")], db, None, at("2026-11-05 04:40"))
    assert report.jobs[0].running and not report.jobs[0].interrupted
    assert report.problems == []


def test_held_cannot_tell_without_the_list(tmp_path):
    path = tmp_path / "lock"
    path.touch()
    assert held(path, tmp_path / "missing") is None


# The report


def test_a_healthy_report(db):
    put(
        db,
        "gc",
        started_at="2026-11-05T04:30:00Z",
        finished_at="2026-11-05T04:31:00Z",
        result="ok",
        exit_code=0,
        ok_at="2026-11-05T04:31:00Z",
    )
    report = collect([job("gc")], db, None, at("2026-11-05 12:00"))
    assert report.problems == []
    status = report.jobs[0]
    assert status.next_run == at("2026-11-06 04:30")
    assert not status.stale and not status.failed and not status.running
    out = text(report)
    assert "gc" in out and "2026-11-06 04:30" in out
    assert "not visible here" in out and "All healthy." in out


def test_a_failed_job_is_a_problem(db):
    put(db, "gc", finished_at="2026-11-05T04:31:00Z", result="failed", exit_code=1)
    report = collect([job("gc")], db, None, at("2026-11-05 12:00"))
    assert report.problems == ["job gc: its last run failed (exit 1)"]


@pytest.mark.parametrize("result", ["paused", "stopped"])
def test_a_pause_or_a_stop_is_not_a_problem(db, result):
    put(
        db,
        "e",
        finished_at="2026-11-05T04:31:00Z",
        result=result,
        exit_code=1,
        ok_at="2026-11-04T04:31:00Z",
    )
    assert collect([job("e")], db, None, at("2026-11-05 12:00")).problems == []


@pytest.mark.parametrize(
    "ok_at,seen_at,now,stale",
    [
        # Daily at 04:30, a 30 s deadline. Last ok yesterday: one missed run is fine
        ("2026-11-04T04:31:00Z", "2026-01-01T00:00:00Z", "2026-11-05 12:00", False),
        # Two missed: stale
        ("2026-11-03T04:31:00Z", "2026-01-01T00:00:00Z", "2026-11-05 12:00", True),
        # The second run still within its deadline (04:30:30) does not count yet
        ("2026-11-03T04:31:00Z", "2026-01-01T00:00:00Z", "2026-11-05 04:30", False),
        # Never a success, but known only since after the last-but-one run
        (None, "2026-11-04T05:00:00Z", "2026-11-05 12:00", False),
        (None, "2026-11-01T05:00:00Z", "2026-11-05 12:00", True),
    ],
)
def test_staleness(db, ok_at, seen_at, now, stale):
    put(db, "gc", ok_at=ok_at, seen_at=seen_at, result="paused", exit_code=1)
    report = collect([job("gc")], db, None, at(now))
    assert report.jobs[0].stale is stale
    assert bool(report.problems) is stale


def test_a_job_never_run_and_unknown_is_not_stale(db):
    report = collect([job("new")], db, None, at("2026-11-05 12:00"))
    assert report.problems == []
    assert "never run" in text(report)


def test_unreadable_records_are_a_problem(tmp_path):
    report = collect([job("gc")], tmp_path / "missing.db", None)
    assert report.error and report.problems == [report.error]
    assert not (tmp_path / "missing.db").exists()  # read only: never made


# The backups


def run(folder, name, complete=True, hours_ago=1.0):
    path = folder / name
    path.mkdir(parents=True)
    if complete:
        marker = path / "COMPLETE"
        marker.touch()
        then = time.time() - hours_ago * 3600
        os.utime(marker, (then, then))


def test_the_newest_complete_run(tmp_path):
    run(tmp_path, "20261105T033000Z", hours_ago=30)
    run(tmp_path, "20261106T033000Z", hours_ago=5)
    run(tmp_path, "20261107T033000Z", complete=False)  # unfinished
    run(tmp_path, "monthly/20261101T035000Z", hours_ago=0.1)
    (tmp_path / "notes").mkdir()
    found = newest_backup(tmp_path)
    assert found.run == "20261106T033000Z"
    assert found.at and datetime.now(UTC) - found.at < timedelta(hours=6)
    assert found.problem(datetime.now(UTC)) is None


def test_a_backup_over_26_hours_old_is_a_problem(tmp_path, db):
    run(tmp_path, "20261105T033000Z", hours_ago=27)
    report = collect([], db, tmp_path)
    assert report.problems == [
        "backups: the newest COMPLETE run, 20261105T033000Z, is over 26 hours old"
    ]


def test_no_complete_run_is_a_problem(tmp_path):
    run(tmp_path, "20261105T033000Z", complete=False)
    assert "no COMPLETE run" in (
        newest_backup(tmp_path).problem(datetime.now(UTC)) or ""
    )


def test_backups_not_in_view_are_not_a_problem():
    assert newest_backup(None) == Backup(None)
    assert Backup(None).problem(datetime.now(UTC)) is None


def test_an_unreadable_backup_folder_is_a_problem(tmp_path):
    found = newest_backup(tmp_path / "missing")
    assert found.error and "cannot read" in (found.problem(datetime.now(UTC)) or "")


# The command


@pytest.fixture
def env(db, tmp_path, monkeypatch):
    backups = tmp_path / "backups"
    run(backups, "20261106T033000Z", hours_ago=2)
    monkeypatch.setenv("SCRAP_DB_PATH", str(db))
    monkeypatch.setenv("SCRAP_BACKUPS", str(backups))
    monkeypatch.setenv(
        "SCRAP_SCHEDULE",
        json.dumps(
            [
                {
                    "name": "gc",
                    "schedule": "30 4 * * *",
                    "timeoutSeconds": 60,
                    "command": ["true"],
                }
            ]
        ),
    )
    return db


def test_status_healthy_exits_0(env, capsys):
    put(env, "gc", result="ok", exit_code=0, ok_at=datetime.now(UTC).isoformat())
    main(["schedule", "status"])
    out = capsys.readouterr().out
    assert "Backups: newest COMPLETE run 20261106T033000Z" in out
    assert "All healthy." in out


def test_status_with_a_failure_exits_1_and_says_so(env, capsys):
    put(env, "gc", result="failed", exit_code=2)
    with pytest.raises(SystemExit) as stopped:
        main(["schedule", "status"])
    assert stopped.value.code == 1
    assert "job gc: its last run failed (exit 2)" in capsys.readouterr().out


def test_status_as_json(env, capsys):
    put(env, "gc", result="ok", exit_code=0, ok_at=datetime.now(UTC).isoformat())
    main(["schedule", "status", "--json"])
    got = json.loads(capsys.readouterr().out)
    assert got["healthy"] is True and got["problems"] == []
    (gc,) = got["jobs"]
    assert gc["name"] == "gc" and gc["last_result"] == "ok" and gc["next_run"]
    assert gc["running"] is False and gc["stale"] is False
    assert got["backup"]["visible"] and got["backup"]["run"] == "20261106T033000Z"


def test_status_refuses_run_and_json_without_status(env):
    with pytest.raises(SystemExit, match="not both"):
        main(["schedule", "status", "--run", "gc"])
    with pytest.raises(SystemExit, match="for status"):
        main(["schedule", "--json"])


# The metrics


def report_with_runs(db, tmp_path):
    put(
        db,
        "gc",
        started_at="2026-11-05T04:30:00Z",
        finished_at="2026-11-05T04:31:00Z",
        result="failed",
        exit_code=1,
        ok_at="2026-11-04T04:31:00Z",
    )
    run(tmp_path / "b", "20261106T033000Z")
    return collect([job("gc"), job("new")], db, tmp_path / "b", at("2026-11-05 12:00"))


def test_the_metrics_text(db, tmp_path):
    body = metrics.render(report_with_runs(db, tmp_path))
    lines = body.splitlines()
    ok = at("2026-11-04 04:31").timestamp()
    assert f'scrap_job_last_success_timestamp_seconds{{job="gc"}} {ok!r}' in lines
    assert 'scrap_job_last_result{job="gc",result="failed"} 1.0' in lines
    assert 'scrap_job_last_result{job="gc",result="ok"} 0.0' in lines
    assert 'scrap_job_failed{job="gc"} 1.0' in lines
    assert 'scrap_job_running{job="new"} 0.0' in lines
    assert 'scrap_job_last_exit_code{job="gc"} 1' in lines
    # A job never run has no times and no result
    assert not any('job="new"' in line and "last_" in line for line in lines)
    nxt = at("2026-11-06 04:30").timestamp()
    assert f'scrap_job_next_run_timestamp_seconds{{job="gc"}} {nxt!r}' in lines
    assert "scrap_backup_visible 1.0" in lines
    assert any(
        x.startswith("scrap_backup_last_complete_timestamp_seconds ") for x in lines
    )
    assert "scrap_schedule_problems 1.0" in lines
    assert "# TYPE scrap_job_stale gauge" in lines


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, ""


def test_the_metrics_are_served(db, tmp_path):
    report = report_with_runs(db, tmp_path)
    server = metrics.serve(0, lambda: report, "127.0.0.1")
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        status, body = get(base + "/metrics")
        assert status == 200 and "scrap_job_failed" in body
        assert get(base + "/")[0] == 404
    finally:
        server.shutdown()
        server.server_close()


def test_a_failed_report_is_a_500_not_a_dead_server(caplog):
    def broken():
        raise sqlite3.OperationalError("locked")

    server = metrics.serve(0, broken, "127.0.0.1")
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        assert get(base + "/metrics")[0] == 500
        assert get(base + "/metrics")[0] == 500  # still answering
    finally:
        server.shutdown()
        server.server_close()
    assert "could not make the report" in caplog.text


def test_the_metrics_listen_on_every_address_dual_stack(db, tmp_path):
    report = report_with_runs(db, tmp_path)
    server = metrics.serve(0, lambda: report)
    try:
        port = server.server_address[1]
        assert get(f"http://127.0.0.1:{port}/metrics")[0] == 200
        if server.address_family == socket.AF_INET6:
            assert get(f"http://[::1]:{port}/metrics")[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_an_idle_connection_is_let_go(db, tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "TIMEOUT", 0.3)
    server = metrics.serve(0, lambda: report_with_runs(db, tmp_path), "127.0.0.1")
    try:
        with socket.create_connection(
            ("127.0.0.1", server.server_address[1]), 5
        ) as idle:
            started = time.monotonic()
            assert idle.recv(1) == b""  # closed by the server, not left waiting
            assert time.monotonic() - started < 4
    finally:
        server.shutdown()
        server.server_close()


def test_metrics_read_the_database_status_does(tmp_path, monkeypatch):
    """No SCRAP_DB_PATH: both fall back to scrap.db in the data folder."""
    Store(tmp_path, tmp_path / "scrap.db").migrate()
    put(tmp_path / "scrap.db", "gc", result="failed", exit_code=4)
    monkeypatch.delenv("SCRAP_DB_PATH", raising=False)
    monkeypatch.delenv("SCRAP_BACKUPS", raising=False)
    monkeypatch.setenv("SCRAP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SCRAP_METRICS_PORT", "1")
    builds = []
    monkeypatch.setattr(metrics, "serve", lambda port, build: builds.append(build))
    metrics.from_env([job("gc")])
    assert builds[0]().jobs[0].failed
    assert schedule_status.paths_from_env()[0] == tmp_path / "scrap.db"


def test_metrics_are_off_unless_a_port_is_set(monkeypatch):
    served = []
    monkeypatch.setattr(metrics, "serve", lambda *a, **k: served.append(a))
    monkeypatch.delenv("SCRAP_METRICS_PORT", raising=False)
    metrics.from_env([])
    assert served == []


def test_a_bad_metrics_port_is_logged_and_the_scheduler_goes_on(monkeypatch, caplog):
    monkeypatch.setenv("SCRAP_METRICS_PORT", "lots")
    metrics.from_env([])
    assert "metrics: not served" in caplog.text


def test_the_records_module_lists_its_results():
    assert set(schedule_record.FAILURES) < set(schedule_record.RESULTS)
    assert Path(lock_path("gc")).name == "scrap-job-gc.lock"
