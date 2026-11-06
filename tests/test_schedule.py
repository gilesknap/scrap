"""scrap schedule and its cron matcher (ADR 46)."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrap import schedule
from scrap.__main__ import main
from scrap.cron import Cron
from scrap.replica import heartbeat_age_hours
from scrap.schedule import BUSY, Job, Scheduler, load
from scrap.store import Store


@pytest.fixture(autouse=True)
def private_locks(tmp_path, monkeypatch):
    """Each test its own /tmp, as the job locks are named for the job."""
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))


def at(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def until(check, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return False


@pytest.mark.parametrize(
    "cron,when,hit",
    [
        ("30 4 * * *", "2026-11-05 04:30", True),
        ("30 4 * * *", "2026-11-05 04:31", False),
        ("11 4 * * 0", "2026-11-08 04:11", True),  # a Sunday
        ("11 4 * * 0", "2026-11-09 04:11", False),
        ("11 4 * * sun", "2026-11-08 04:11", True),
        ("11 4 * * SUN", "2026-11-08 04:11", True),
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
        # Both day fields restricted: either, as cron has it
        ("0 0 13 * fri", "2026-11-13 00:00", True),
        ("0 0 13 * fri", "2026-11-06 00:00", True),
        ("0 0 13 * fri", "2026-11-07 00:00", False),
        # robfig's starBit: a star part with step 1 or none means "any day", so only the
        # other field decides. These are Fridays only.
        ("0 0 */1 * fri", "2026-11-06 00:00", True),
        ("0 0 */1 * fri", "2026-11-07 00:00", False),
        ("0 0 *,5 * fri", "2026-11-05 00:00", False),
        ("0 0 ?,5 * fri", "2026-11-05 00:00", False),
        # A step over 1 is not a star: the 1st, 3rd ... or a Friday
        ("0 0 */2 * fri", "2026-11-07 00:00", True),
        ("0 0 */2 * fri", "2026-11-08 00:00", False),
        ("0 0 13 * */1", "2026-11-13 00:00", True),
        ("0 0 13 * */1", "2026-11-14 00:00", False),
        # Weekdays are 0 to 6: 1/2 is 1, 3 and 5, and never Sunday
        ("0 0 * * 1/2", "2026-11-09 00:00", True),  # Monday
        ("0 0 * * 1/2", "2026-11-08 00:00", False),  # Sunday
        # Empty parts are dropped, as robfig's FieldsFunc does
        ("1,,2 * * * *", "2026-11-05 07:02", True),
        (",1 * * * *", "2026-11-05 07:01", True),
        # Only a comma: valid, and never fires
        (", * * * *", "2026-11-05 07:01", False),
    ],
)
def test_cron(cron, when, hit):
    assert Cron(cron).matches(at(when)) is hit


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "* * * *",
        "* * * * * *",
        "61 * * * *",
        "* 24 * * *",
        "a b c d e",
        "*/0 * * * *",
        "5-1 * * * *",
        "* * * * 7",  # robfig's weekdays stop at 6
        "1-2-3 * * * *",
        "1/2/3 * * * *",
        "1_0 * * * *",
        "+5 * * * *",
        "٣ * * * *",  # Arabic-Indic three: int() would take it
        "@every 1h",
        "@sometimes",
        "@DAILY",  # robfig's descriptors are exact
        " @daily",
    ],
)
def test_cron_refuses(bad):
    with pytest.raises(ValueError):
        Cron(bad)


def job(name="j", cron="* * * * *", command=None, timeout=30.0, zone=None, **kw):
    return Job(name, Cron(cron), zone, timeout, command or ["true"], **kw)


LONDON = ZoneInfo("Europe/London")


def fires(cron, start, minutes):
    """Local times this job fires at, walking real minutes from a UTC time."""
    j = job(cron=cron, zone=LONDON)
    return [
        (start + timedelta(minutes=i)).astimezone(LONDON).strftime("%H:%M %Z")
        for i in range(minutes)
        if j.due(start + timedelta(minutes=i))
    ]


def test_a_dst_gap_skips_the_time_as_robfig_does():
    # 2026-03-29 01:00 GMT jumps to 02:00 BST: 01:30 never happens that night
    assert fires("30 1 * * *", at("2026-03-29 00:00"), 180) == []
    assert fires("30 2 * * *", at("2026-03-29 00:00"), 180) == ["02:30 BST"]


def test_a_dst_fold_fires_twice_as_robfig_does():
    # 2026-10-25 02:00 BST falls back to 01:00 GMT: 01:30 happens twice, and robfig's
    # Next, walking real time, finds both
    assert fires("30 1 * * *", at("2026-10-24 23:00"), 240) == [
        "01:30 BST",
        "01:30 GMT",
    ]


def test_load_leaves_out_a_bad_schedule_and_keeps_the_rest(caplog):
    text = json.dumps(
        [
            {"name": "bad", "schedule": "nope", "timeoutSeconds": 1, "command": ["x"]},
            {
                "name": "zone",
                "schedule": "* * * * *",
                "timeZone": "No/Where",
                "timeoutSeconds": 1,
                "command": ["x"],
            },
            {
                "name": "ok",
                "schedule": "30 4 * * *",
                "timeZone": "Europe/London",
                "timeoutSeconds": 5,
                "command": ["x"],
            },
        ]
    )
    jobs = load(text)
    assert [j.name for j in jobs] == ["ok"]
    assert "job bad will not run" in caplog.text
    assert "job zone will not run" in caplog.text


@pytest.mark.parametrize(
    "item",
    [
        {"name": "bad", "schedule": "nope"},
        {"name": "bad", "schedule": "* * * * *", "timeZone": "No/Where"},
        {"name": "bad", "schedule": "@every 1h"},
    ],
)
def test_load_strict_refuses(item):
    with pytest.raises(ValueError, match="job bad"):
        load(json.dumps([{"timeoutSeconds": 1, "command": ["x"], **item}]), strict=True)


def test_a_job_follows_its_time_zone():
    jobs = load(
        json.dumps(
            [
                {
                    "name": "z",
                    "schedule": "30 4 * * *",
                    "timeZone": "Asia/Tokyo",
                    "timeoutSeconds": 1,
                    "command": ["true"],
                }
            ]
        )
    )
    assert jobs[0].due(at("2026-11-04 19:30"))
    assert not jobs[0].due(at("2026-11-05 04:30"))


def test_an_empty_time_zone_is_utc():
    jobs = load(
        json.dumps(
            [
                {
                    "name": "z",
                    "schedule": "30 4 * * *",
                    "timeZone": "",
                    "timeoutSeconds": 1,
                    "command": ["true"],
                }
            ]
        )
    )
    assert jobs[0].due(at("2026-11-05 04:30"))


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


def test_a_job_that_cannot_start_is_a_failure_not_a_dead_thread(monkeypatch, caplog):
    said = []
    monkeypatch.setattr(schedule, "notify", said.append)
    sched = Scheduler([job(command=["/no/such/program"])])
    sched.tick(at("2026-11-05 04:30"))
    sched.threads[0].join(5)
    assert "could not start" in caplog.text
    assert said == ["scrap: scheduled job j failed"]
    assert sched.running == {}  # free for its next time


def enrich_like(tmp_path, line, code=1):
    script = tmp_path / "enrich.py"
    script.write_text(
        f"import sys\nprint({line!r}, file=sys.stderr)\nsys.exit({code})\n"
    )
    return job("enrich", command=[sys.executable, str(script)], pausable=True)


def test_a_queue_pause_is_not_a_failure(tmp_path, monkeypatch, caplog):
    said = []
    monkeypatch.setattr(schedule, "notify", said.append)
    pausing = enrich_like(tmp_path, "stopped: the queue is paused (budget)")
    assert Scheduler([]).run_job(pausing) == 1
    assert said == []
    assert "queue pause" in caplog.text


def test_any_other_exit_of_a_pausable_job_is_a_failure(tmp_path, monkeypatch):
    said = []
    monkeypatch.setattr(schedule, "notify", said.append)
    assert Scheduler([]).run_job(enrich_like(tmp_path, "boom")) == 1
    assert said == ["scrap: scheduled job enrich failed"]


def test_a_job_past_its_deadline_is_stopped(monkeypatch, caplog):
    monkeypatch.setattr(schedule, "notify", lambda m: None)
    code = Scheduler([]).run_job(job(command=["sleep", "30"], timeout=0.2))
    assert code != 0
    assert "deadline" in caplog.text


def test_stop_kills_one_that_ignores_sigterm(monkeypatch):
    monkeypatch.setattr(schedule, "STOP_SECONDS", 0.5)
    code = (
        "import signal,time;signal.signal(15,signal.SIG_IGN);"
        "print('up',flush=True);time.sleep(30)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code], start_new_session=True, stdout=subprocess.PIPE
    )
    assert proc.stdout
    proc.stdout.readline()
    start = time.monotonic()
    assert schedule._stop(proc) == -signal.SIGKILL
    assert time.monotonic() - start < 10
    proc.stdout.close()


def test_stop_reaches_a_grandchild(tmp_path):
    pid_file = tmp_path / "pid"
    proc = subprocess.Popen(
        ["/bin/sh", "-c", f"sleep 30 & echo $! > {pid_file}; wait"],
        start_new_session=True,
    )
    assert until(lambda: pid_file.exists() and pid_file.read_text().strip())
    pid = int(pid_file.read_text())
    schedule._stop(proc)

    def gone():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        # A zombie awaiting its reaper counts as gone
        return Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"

    assert until(gone)


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


def test_back_to_back_ticks_start_one_run(caplog):
    """The name is taken in tick, before the thread has started anything."""
    sched = Scheduler([job("slow", command=["sleep", "30"])])
    sched.tick(at("2026-11-05 04:30"))
    sched.tick(at("2026-11-05 04:31"))
    assert len(sched.threads) == 1
    assert "still running" in caplog.text
    assert until(lambda: sched.running.get("slow"))
    running = sched.running["slow"]
    assert running
    schedule._stop(running)
    sched.threads[0].join(5)


def test_a_gap_fires_a_job_once(tmp_path):
    log = tmp_path / "log"
    sched = Scheduler(
        [job("each", "* * * * *", ["sh", "-c", f"echo x >> {log}"])],
    )
    sched.tick(at("2026-11-05 04:40"), at("2026-11-05 04:30"))
    sched.threads[0].join(5)
    assert log.read_text() == "x\n"


def test_a_gap_fires_a_job_due_inside_it_not_only_at_its_end(tmp_path):
    out = tmp_path / "ran"
    sched = Scheduler([job("mid", "35 4 * * *", ["touch", str(out)])])
    sched.tick(at("2026-11-05 04:40"), at("2026-11-05 04:30"))
    sched.threads[0].join(5)
    assert out.exists()


def test_a_gap_past_catch_up_is_only_noted(monkeypatch, caplog, tmp_path):
    """Run's own loop, with its clock jumped forward by more than CATCH_UP."""
    out = tmp_path / "ran"
    sched = Scheduler([job("old", "35 4 * * *", ["touch", str(out)])])
    times = iter(
        [
            at("2026-11-05 04:30"),  # the start
            at("2026-11-05 04:30"),  # for the sleep
            at("2026-11-05 07:00"),  # after a long stall
        ]
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            try:
                return next(times)
            except StopIteration:
                sched.stopping = True
                return at("2026-11-05 07:00")

    monkeypatch.setattr(schedule, "datetime", Clock)
    monkeypatch.setattr(schedule.Scheduler, "_sleep", lambda self, s: None)
    sched.run()
    assert "nothing ran from" in caplog.text
    assert not out.exists()  # 04:35 is further back than a CronJob's deadline


def test_a_gap_past_catch_up_still_runs_a_time_within_it(monkeypatch, tmp_path):
    """As a CronJob with startingDeadlineSeconds: 3600, the latest time missed is run
    if it is within the hour."""
    started = []
    monkeypatch.setattr(
        schedule.Scheduler, "run_job", lambda self, j: started.append(j.name)
    )
    sched = Scheduler([job("recent", "30 6 * * *"), job("old", "59 5 * * *")])
    times = iter(
        [
            at("2026-11-05 04:30"),  # the start
            at("2026-11-05 04:30"),  # for the sleep
            at("2026-11-05 07:00"),  # after a long stall
        ]
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            try:
                return next(times)
            except StopIteration:
                sched.stopping = True
                return at("2026-11-05 07:00")

    monkeypatch.setattr(schedule, "datetime", Clock)
    monkeypatch.setattr(schedule.Scheduler, "_sleep", lambda self, s: None)
    sched.run()
    for thread in sched.threads:
        thread.join(5)
    # 06:30 is within the hour; 05:59 is not (back to 06:00, which is exclusive)
    assert started == ["recent"]


def test_stop_jobs_stops_them_all_at_once(monkeypatch, tmp_path):
    """Several jobs that ignore SIGTERM: one STOP_SECONDS for all, not one each, so
    Litestream's last sync gets its window."""
    monkeypatch.setattr(schedule, "STOP_SECONDS", 1)
    monkeypatch.setattr(schedule, "STOP_ALL_SECONDS", 3)
    names = ["a", "b", "c", "d"]
    code = (
        "import pathlib,signal,sys,time;signal.signal(15,signal.SIG_IGN);"
        "pathlib.Path(sys.argv[1]).touch();time.sleep(60)"
    )
    sched = Scheduler(
        [
            job(name, command=[sys.executable, "-c", code, str(tmp_path / name)])
            for name in names
        ]
    )
    sched.tick(at("2026-11-05 04:30"))
    # Each running, and ignoring SIGTERM
    assert until(
        lambda: all((tmp_path / n).exists() and sched.running.get(n) for n in names), 30
    )
    procs = list(sched.running.values())
    start = time.monotonic()
    sched.stopping = True
    sched.stop_jobs()
    took = time.monotonic() - start
    assert took < 2.5  # one at a time would be over 4
    assert all(p and p.returncode == -signal.SIGKILL for p in procs)
    assert not any(t.is_alive() for t in sched.threads)


def test_finished_threads_are_let_go():
    sched = Scheduler([job("quick", "* * * * *")])
    for minute in range(3):
        sched.tick(at("2026-11-05 04:30") + timedelta(minutes=minute))
        sched.threads[-1].join(5)
    sched.tick(at("2026-11-05 04:40"))
    assert len(sched.threads) == 1


def test_a_restart_inside_a_jobs_minute_does_not_run_it_again(tmp_path, monkeypatch):
    """The minute it started in is not a tick."""
    out = tmp_path / "ran"
    now = datetime.now(UTC)
    cron = f"{now.minute} {now.hour} * * *"
    sched = Scheduler([job("this-minute", cron, ["touch", str(out)])])

    def stop_soon(self, seconds):
        self.stopping = True

    monkeypatch.setattr(schedule.Scheduler, "_sleep", stop_soon)
    sched.run()
    assert not out.exists() or now.minute != datetime.now(UTC).minute


def test_stopping_stops_a_job_and_the_loop(tmp_path):
    sched = Scheduler([job("slow", command=["sleep", "30"])])
    sched.tick(at("2026-11-05 04:30"))
    assert until(lambda: sched.running.get("slow"))
    runner = threading.Thread(target=sched.run)
    runner.start()
    start = time.monotonic()
    sched.stop()
    runner.join(15)
    assert not runner.is_alive()
    assert time.monotonic() - start < 12


def test_it_stamps_the_database_at_most_every_so_often(tmp_path, monkeypatch):
    store = Store(tmp_path, tmp_path / "s.db")
    store.migrate()
    calls = []
    monkeypatch.setattr(schedule, "beat", lambda db: calls.append(db) or 1)
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
        [
            {"name": n, "schedule": "0 0 1 1 *", "timeoutSeconds": 30, "command": c}
            for n, c in jobs
        ]
    )


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


def test_run_refuses_a_job_already_running(tmp_path, monkeypatch):
    lock = schedule._lock("busy")
    assert lock is not None
    monkeypatch.setenv("SCRAP_SCHEDULE", text(("busy", ["true"])))
    with pytest.raises(SystemExit) as stopped:
        main(["schedule", "--run", "busy"])
    assert stopped.value.code == BUSY
    lock.close()


def _scrap(env, *args):
    return subprocess.Popen(
        [sys.executable, "-m", "scrap", "schedule", *args],
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def test_a_real_sigterm_stops_the_scheduler_and_its_job(tmp_path):
    """Through from_env's own handler, with a job that is running."""
    pid_file = tmp_path / "pid"
    cron = "* * * * *"
    env = {
        "TMPDIR": str(tmp_path),
        "SCRAP_SCHEDULE": json.dumps(
            [
                {
                    "name": "long",
                    "schedule": cron,
                    "timeoutSeconds": 300,
                    "command": ["sh", "-c", f"echo $$ > {pid_file}; exec sleep 300"],
                }
            ]
        ),
    }
    proc = _scrap(env)
    assert proc.stdout
    line = proc.stdout.readline()  # said once its handlers are in place
    assert "running: long" in line
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=30)
    assert proc.returncode == 0, out


def test_a_real_sigterm_stops_a_run_now_and_its_job(tmp_path):
    pid_file = tmp_path / "pid"
    env = {
        "TMPDIR": str(tmp_path),
        "SCRAP_SCHEDULE": text(
            ("long", ["sh", "-c", f"echo $$ > {pid_file}; exec sleep 300"])
        ),
    }
    proc = _scrap(env, "--run", "long")
    assert until(lambda: pid_file.exists() and pid_file.read_text().strip(), 20)
    pid = int(pid_file.read_text())
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=30)
    assert proc.returncode == 128 + signal.SIGTERM

    def gone():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"

    assert until(gone)
