"""scrap schedule: the jobs that must see the live database, in the scrap pod (ADR 46).

With Litestream the database is on the pod's emptyDir, so gc and the Claude passes
cannot be CronJobs: they run here, in a container beside scrap, on the schedules the
chart would give the CronJobs. $SCRAP_SCHEDULE is their list, as JSON:

    [{"name": "gc", "schedule": "30 4 * * *", "timeZone": "", "timeoutSeconds": 3600,
      "command": ["/bin/sh", "-ec", "..."]}]

An empty timeZone is UTC here, not the cluster controller's zone.

As with a CronJob's concurrencyPolicy: Forbid, a job still running at its next time is
not started again, and after a gap one run stands for all the times missed in it, if
one of them is within the last 60 minutes (a CronJob's startingDeadlineSeconds). A
per-job lock makes that hold for --run too. A job's failure is logged, pushed to
SCRAP_NOTIFY_URL if set, and never stops the scheduler. A time missed while this was
not running is not made up, and a rollout stops a running job: the next run carries on.

It also stamps the database every 15 minutes, for the backup jobs (replica.beat), and
watches that the stamps reach the replica (watch.py). Each job's runs are recorded in
the database (schedule_record.py), for scrap schedule status and the metrics (#558).
"""

import fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO
from zoneinfo import ZoneInfo

from .cron import Cron
from .dbstate import parse_size
from .notify import notify
from .replica import beat
from .schedule_record import (
    DEADLINE,
    FAILED,
    NOT_STARTED,
    OK,
    STOPPED,
    finished,
    lock_path,
    seen,
    started,
)
from .schedule_record import PAUSED as PAUSED_RESULT
from .watch import Watch

__all__ = ["Job", "Scheduler", "from_env", "load"]

log = logging.getLogger("scrap.schedule")

BEAT = timedelta(minutes=15)
CATCH_UP = timedelta(minutes=60)  # as the CronJobs' startingDeadlineSeconds
STOP_SECONDS = 10  # a job asked to stop, before it is killed
# Every job, together, at a pod's end: Litestream's last sync waits on this container
STOP_ALL_SECONDS = 15
BUSY = 75  # EX_TEMPFAIL: --run found the job already running
PAUSED = "stopped: the queue is paused"  # scrap enrich's last line at a pause or budget


@dataclass
class Job:
    name: str
    cron: Cron
    zone: ZoneInfo | None
    timeout: float
    command: list[str]
    pausable: bool = False  # stopping at a queue pause or spent budget is not a failure

    def due(self, minute: datetime) -> bool:
        return self.cron.matches(minute.astimezone(self.zone) if self.zone else minute)


def load(text: str, strict: bool = False) -> list[Job]:
    """The jobs in text. Strict (scrap db-init, so a bad one stops the rollout): a bad
    schedule or time zone raises ValueError. Otherwise one is logged and left out, and
    the rest carry on."""
    jobs = []
    for item in json.loads(text):
        try:
            zone = ZoneInfo(item["timeZone"]) if item.get("timeZone") else None
            cron = Cron(item["schedule"])
        except (ValueError, KeyError, OSError) as error:
            if strict:
                raise ValueError(f"job {item.get('name')}: {error}") from None
            log.error("job %s will not run: %s", item.get("name"), error)
            continue
        jobs.append(
            Job(
                item["name"],
                cron,
                zone,
                item["timeoutSeconds"],
                item["command"],
                item.get("pausable", False),
            )
        )
    return jobs


def _lock(name: str) -> IO[str] | None:
    """The job's lock in /tmp, shared with scrap schedule --run; None if it is held."""
    lock = open(lock_path(name), "w")  # noqa: SIM115
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


class Relay:
    """Pass a job's stderr on as it comes, keeping its last line."""

    def __init__(self, proc: subprocess.Popen):
        self.proc = proc
        self.last = ""
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        assert self.proc.stderr
        with self.proc.stderr as stream:
            for line in stream:
                sys.stderr.write(line)
                sys.stderr.flush()
                self.last = line

    def end(self) -> str:
        """The last line. Not waiting long: a stray child may hold the pipe open."""
        self.thread.join(2)
        return self.last


class Scheduler:
    def __init__(
        self, jobs: list[Job], db: Path | None = None, watch: Watch | None = None
    ):
        self.jobs = jobs
        self.db = db
        self.watch = watch
        # A name here is taken; its process once it has one
        self.running: dict[str, subprocess.Popen | None] = {}
        self.threads: list[threading.Thread] = []
        self.lock = threading.Lock()
        self.stopping = False  # a plain flag: set from the signal handler
        self.last_beat: datetime | None = None
        self.seen = False  # the jobs are in the database's records

    def _start(self, job: Job) -> tuple[subprocess.Popen, Relay | None]:
        """The job's process; a pausable one's stderr is passed on, and its end kept."""
        if not job.pausable:
            return subprocess.Popen(job.command, start_new_session=True), None
        proc = subprocess.Popen(
            job.command,
            start_new_session=True,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
        return proc, Relay(proc)

    def run_job(self, job: Job) -> int:
        """Run a job to its end or its deadline; its exit status."""
        try:
            lock = _lock(job.name)
        except OSError as error:
            return self._not_started(job, error)
        if lock is None:
            with self.lock:
                self.running.pop(job.name, None)
            log.warning("job %s: already running, not starting another", job.name)
            return BUSY
        with lock:
            log.info("job %s: starting", job.name)
            started(self.db, job.name)
            try:
                proc, relay = self._start(job)
            except OSError as error:
                return self._not_started(job, error)
            with self.lock:
                self.running[job.name] = proc
            late = False
            try:
                code = proc.wait(job.timeout)
            except subprocess.TimeoutExpired:
                log.error("job %s: stopped at its %ss deadline", job.name, job.timeout)
                late = True
                code = _stop(proc) or 1
            finally:
                with self.lock:
                    self.running.pop(job.name, None)
            code = 128 - code if code < 0 else code  # as a shell reports a signal
            result = self._report(job, code, relay.end() if relay else "", late)
            finished(self.db, job.name, result, code)
        return code

    def _not_started(self, job: Job, error: OSError) -> int:
        with self.lock:
            self.running.pop(job.name, None)
        log.error("job %s: could not start: %s", job.name, error)
        notify(f"scrap: scheduled job {job.name} failed")
        finished(self.db, job.name, NOT_STARTED, 127)
        return 127

    def _report(self, job: Job, code: int, last: str, late: bool = False) -> str:
        """Log (and notify) how the run ended; that, as a schedule_record result."""
        if self.stopping and code:
            log.info("job %s: stopped with the pod", job.name)
            return STOPPED
        if code and last.startswith(PAUSED):
            log.warning("job %s: stopped at a queue pause or spent budget", job.name)
            return PAUSED_RESULT
        if code:
            log.error("job %s: failed, exit %s", job.name, code)
            notify(f"scrap: scheduled job {job.name} failed")
            return DEADLINE if late else FAILED
        log.info("job %s: done", job.name)
        return OK

    def note_jobs(self) -> None:
        """Until it has worked once (scrap serve may not have made the table yet), put
        each job in the records, so that its staleness counts from now."""
        if not self.seen:
            self.seen = seen(self.db, [j.name for j in self.jobs])

    def tick(self, minute: datetime, since: datetime | None = None) -> None:
        """Start whatever was due after since (default: only at minute) and up to
        minute, each job at most once, and stamp the database if due."""
        self.stamp(minute)
        if self.watch:
            self.watch.check()
        self.note_jobs()
        self.threads = [t for t in self.threads if t.is_alive()]
        count = int((minute - since) / timedelta(minutes=1)) if since else 1
        minutes = [minute - timedelta(minutes=i) for i in range(count)]
        for job in self.jobs:
            if any(job.due(m) for m in minutes):
                with self.lock:
                    busy = job.name in self.running
                    if not busy:
                        self.running[job.name] = None
                if busy:
                    log.warning("job %s: still running, skipping this time", job.name)
                    continue
                thread = threading.Thread(target=self.run_job, args=(job,), daemon=True)
                thread.start()
                self.threads.append(thread)

    def stamp(self, now: datetime | None = None) -> None:
        """If it is time (no now: at once), stamp the database, for the backups' check
        and the next start's."""
        if not self.db or (now and self.last_beat and now - self.last_beat < BEAT):
            return
        try:
            stamped = beat(self.db)
            self.last_beat = now or datetime.now(UTC)
            if self.watch:
                self.watch.stamped(stamped)
        except Exception:  # noqa: BLE001  a missed stamp shows at the next check
            log.exception("could not stamp the database")

    def _sleep(self, seconds: float) -> None:
        """Sleep, but not a second past being told to stop."""
        end = time.monotonic() + seconds
        while not self.stopping and (left := end - time.monotonic()) > 0:
            time.sleep(min(left, 1))

    def run(self) -> None:
        """Until told to stop: each new minute, a gap firing a job once if it was due
        within the last CATCH_UP. The minute this started in is not one: a restart
        inside a job's minute does not run it twice."""
        last = _minute(datetime.now(UTC))
        self.stamp()
        self.note_jobs()
        if self.watch:
            self.watch.check()
        while not self.stopping:
            self._sleep(60 - datetime.now(UTC).second)
            minute = _minute(datetime.now(UTC))
            if self.stopping or minute <= last:
                continue
            if minute - last > CATCH_UP:
                log.warning(
                    "nothing ran from %s to %s: times before %s are not made up",
                    last,
                    minute,
                    minute - CATCH_UP,
                )
                last = minute - CATCH_UP
            self.tick(minute, last)
            last = minute
        # The last stamp: if the replica lacks it, the final sync did not land
        self.stamp()
        self.stop_jobs()

    def run_now(self, job: Job) -> int:
        """scrap schedule --run: the job in a thread, so a signal can stop it here."""
        result: list[int] = []
        thread = threading.Thread(target=lambda: result.append(self.run_job(job)))
        thread.start()
        while thread.is_alive():
            if self.stopping:
                self.stop_jobs()
            thread.join(0.2)
        return result[0]

    def stop_jobs(self) -> None:
        """SIGTERM to every running job at once, SIGKILL to any left after STOP_SECONDS,
        and the lot within STOP_ALL_SECONDS: the native sidecar, and so Litestream's
        last sync, is only told to stop once this container has ended."""
        deadline = time.monotonic() + STOP_ALL_SECONDS
        kill_at = time.monotonic() + STOP_SECONDS
        with self.lock:
            procs = [p for p in self.running.values() if p]
        for proc in procs:
            _signal(proc, signal.SIGTERM)
        for proc in procs:
            try:
                proc.wait(max(0, kill_at - time.monotonic()))
            except subprocess.TimeoutExpired:
                _signal(proc, signal.SIGKILL)
        for proc in procs:
            try:
                proc.wait(max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                log.error("job process %s: still there after SIGKILL", proc.pid)
        for thread in self.threads:
            thread.join(max(0, deadline - time.monotonic()))

    def stop(self, *_: object) -> None:
        self.stopping = True


def _minute(at: datetime) -> datetime:
    return at.replace(second=0, microsecond=0)


def _signal(proc: subprocess.Popen, number: signal.Signals) -> None:
    """The signal to the job's whole process group, unless it has already ended."""
    if proc.returncode is None:
        try:
            os.killpg(proc.pid, number)
        except ProcessLookupError:
            pass


def _stop(proc: subprocess.Popen) -> int:
    """SIGTERM to the job's whole process group, then SIGKILL. Its exit status."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            return proc.wait(STOP_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return proc.wait()


def _watch(db: str | None) -> Watch | None:
    replica = os.environ.get("SCRAP_LITESTREAM_REPLICA")
    data = os.environ.get("SCRAP_DATA_DIR")
    if not (db and replica and data):
        return None
    limit = os.environ.get("SCRAP_DB_SIZE_LIMIT")
    return Watch(
        Path(db), Path(data), Path(replica), parse_size(limit) if limit else None
    )


def from_env(
    run: str | None = None,
    beside: Callable[[list[Job]], None] | None = None,
) -> None:
    """scrap schedule, or with run one job now, exiting with its status. beside is
    started with the jobs before the scheduler runs (the metrics)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    jobs = load(os.environ.get("SCRAP_SCHEDULE", "[]"))
    db = os.environ.get("SCRAP_DB_PATH")
    signals = (signal.SIGTERM, signal.SIGINT)
    if run:
        scheduler = Scheduler(jobs, Path(db) if db else None)
        for job in jobs:
            if job.name == run:
                for number in signals:
                    signal.signal(number, scheduler.stop)
                code = scheduler.run_now(job)
                if code:
                    raise SystemExit(code)
                return
        raise SystemExit(f"scrap schedule: no job {run}: {[j.name for j in jobs]}")
    scheduler = Scheduler(jobs, Path(db) if db else None, _watch(db))
    for number in signals:
        signal.signal(number, scheduler.stop)
    if beside:
        beside(jobs)
    log.info("running: %s", ", ".join(j.name for j in jobs) or "only the heartbeat")
    scheduler.run()
