"""scrap schedule: the jobs that must see the live database, in the scrap pod (ADR 46).

With Litestream the database is on the pod's emptyDir, so gc and the Claude passes
cannot be CronJobs: they run here, in a container beside scrap, on the schedules the
chart would give the CronJobs. $SCRAP_SCHEDULE is their list, as JSON:

    [{"name": "gc", "schedule": "30 4 * * *", "timeZone": "", "timeoutSeconds": 3600,
      "command": ["/bin/sh", "-ec", "..."]}]

As with a CronJob's concurrencyPolicy: Forbid, a job still running at its next time is
not started again. A job's failure is logged, pushed to SCRAP_NOTIFY_URL if set, and
never stops the scheduler (a container that exits takes the pod out of its Service). A
time missed while this was not running is not made up: the next one carries on, as the
jobs all allow.

It also stamps the database every few minutes, for the backup jobs (replica.beat).
"""

import json
import logging
import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .cron import Cron
from .notify import notify
from .replica import beat

__all__ = ["Job", "Scheduler", "from_env", "load"]

log = logging.getLogger("scrap.schedule")

BEAT = timedelta(minutes=15)
CATCH_UP = timedelta(minutes=60)  # as the CronJobs' startingDeadlineSeconds
STOP_SECONDS = 10  # a job asked to stop, before it is killed


@dataclass
class Job:
    name: str
    cron: Cron
    zone: ZoneInfo | None
    timeout: float
    command: list[str]

    def due(self, minute: datetime) -> bool:
        return self.cron.matches(minute.astimezone(self.zone) if self.zone else minute)


def load(text: str) -> list[Job]:
    """The jobs in text. One with a bad schedule is logged and left out: the rest, and
    the pod, carry on."""
    jobs = []
    for item in json.loads(text):
        try:
            zone = ZoneInfo(item["timeZone"]) if item.get("timeZone") else None
            cron = Cron(item["schedule"])
        except (ValueError, KeyError, OSError) as error:
            log.error("job %s will not run: %s", item.get("name"), error)
            continue
        jobs.append(
            Job(item["name"], cron, zone, item["timeoutSeconds"], item["command"])
        )
    return jobs


class Scheduler:
    def __init__(self, jobs: list[Job], db: Path | None = None):
        self.jobs = jobs
        self.db = db
        self.running: dict[str, subprocess.Popen] = {}
        self.threads: list[threading.Thread] = []
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.last_beat: datetime | None = None

    def run_job(self, job: Job) -> int:
        """Run a job to its end or its deadline; its exit status."""
        log.info("job %s: starting", job.name)
        proc = subprocess.Popen(job.command, start_new_session=True)
        with self.lock:
            self.running[job.name] = proc
        try:
            code = proc.wait(job.timeout)
        except subprocess.TimeoutExpired:
            log.error("job %s: stopped at its %ss deadline", job.name, job.timeout)
            code = _stop(proc) or 1
        finally:
            with self.lock:
                self.running.pop(job.name, None)
        if self.stopping.is_set():
            log.info("job %s: stopped with the pod", job.name)
        elif code:
            log.error("job %s: failed, exit %s", job.name, code)
            notify(f"scrap: scheduled job {job.name} failed")
        else:
            log.info("job %s: done", job.name)
        return code

    def tick(self, minute: datetime) -> None:
        """Start whatever is due at this minute, and stamp the database if due."""
        self.stamp(minute)
        for job in self.jobs:
            if job.due(minute):
                with self.lock:
                    busy = job.name in self.running
                if busy:
                    log.warning("job %s: still running, skipping this time", job.name)
                    continue
                thread = threading.Thread(target=self.run_job, args=(job,), daemon=True)
                thread.start()
                self.threads.append(thread)

    def stamp(self, now: datetime) -> None:
        if not self.db or (self.last_beat and now - self.last_beat < BEAT):
            return
        try:
            beat(self.db)
            self.last_beat = now
        except Exception:  # noqa: BLE001  a missed stamp shows at the next backup
            log.exception("could not stamp the database")

    def run(self) -> None:
        """Until told to stop: each minute in turn, none twice, gaps up to CATCH_UP."""
        last = _minute(datetime.now(UTC)) - timedelta(minutes=1)
        while not self.stopping.is_set():
            now = datetime.now(UTC)
            minute = _minute(now)
            if minute - last > CATCH_UP:
                log.warning("nothing ran from %s to %s", last, minute)
                last = minute - timedelta(minutes=1)
            while last < minute:
                last += timedelta(minutes=1)
                self.tick(last)
            wait = 60 - (datetime.now(UTC) - minute).total_seconds()
            self.stopping.wait(max(wait, 0.1))
        with self.lock:
            procs = list(self.running.values())
        for proc in procs:
            _stop(proc)
        for thread in self.threads:
            thread.join(STOP_SECONDS)

    def stop(self, *_: object) -> None:
        self.stopping.set()


def _minute(at: datetime) -> datetime:
    return at.replace(second=0, microsecond=0)


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


def from_env(run: str | None = None) -> None:
    """scrap schedule, or with run one job now, exiting with its status."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    jobs = load(os.environ.get("SCRAP_SCHEDULE", "[]"))
    db = os.environ.get("SCRAP_DB_PATH")
    scheduler = Scheduler(jobs, Path(db) if db else None)
    if run:
        for job in jobs:
            if job.name == run:
                code = scheduler.run_job(job)
                if code:
                    raise SystemExit(code)
                return
        raise SystemExit(f"scrap schedule: no job {run}: {[j.name for j in jobs]}")
    signal.signal(signal.SIGTERM, scheduler.stop)
    signal.signal(signal.SIGINT, scheduler.stop)
    log.info("running: %s", ", ".join(j.name for j in jobs) or "only the heartbeat")
    scheduler.run()
