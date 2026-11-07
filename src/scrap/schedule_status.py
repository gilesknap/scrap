"""scrap schedule status (#558): how each of scrap schedule's jobs last ran, when it
runs next, and the newest backup run with a COMPLETE marker, in one place. Run in the
jobs container (kubectl exec); its exit status makes it usable as a probe. The metrics
(metrics.py) read the same report.

A problem, which makes the exit status 1:

- a job whose last run failed (a non-zero exit, its deadline, or it could not start);
- a stale job: neither of its last two runs that should have finished by now (each
  scheduled time plus the job's deadline) succeeded. It counts from when the scheduler
  first knew the job, so a new job is not stale. A Claude pass stopped at a queue pause
  or spent budget is not a failure, but it is not a success either: a pause that lasts
  two runs makes the pass stale;
- a backup folder in view whose newest COMPLETE run is over 26 hours old, or that has
  none: past that, gc only counts;
- records that cannot be read.
"""

import itertools
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .backup import COMPLETE, RUN
from .schedule import Job, load
from .schedule_record import (
    DEADLINE,
    FAILURES,
    NOT_STARTED,
    Record,
    held,
    lock_path,
    read,
)

__all__ = [
    "BACKUP_STALE",
    "Backup",
    "JobStatus",
    "Report",
    "as_json",
    "collect",
    "from_env",
    "newest_backup",
    "paths_from_env",
    "text",
]

BACKUP_STALE = timedelta(hours=26)  # as gc's check: older than this, gc only counts
HOW = {DEADLINE: "was stopped at its deadline", NOT_STARTED: "could not start"}


@dataclass
class Backup:
    """The newest daily backup run with a COMPLETE marker, in folder."""

    folder: Path | None  # None: no backup folder is in view here
    run: str | None = None
    at: datetime | None = None  # its COMPLETE marker's time
    error: str | None = None

    def problem(self, at: datetime) -> str | None:
        if self.folder is None:
            return None
        if self.error:
            return f"backups: cannot read {self.folder}: {self.error}"
        if self.at is None:
            return f"backups: no COMPLETE run in {self.folder}"
        if at - self.at > BACKUP_STALE:
            return f"backups: the newest COMPLETE run, {self.run}, is over 26 hours old"
        return None


def newest_backup(folder: Path | None) -> Backup:
    """The newest run in folder (not monthly/) with its COMPLETE marker."""
    if folder is None:
        return Backup(None)
    try:
        runs = sorted((n for n in os.listdir(folder) if RUN.fullmatch(n)), reverse=True)
        for run in runs:
            try:
                stat = (folder / run / COMPLETE).stat()
            except FileNotFoundError:
                continue
            return Backup(folder, run, datetime.fromtimestamp(stat.st_mtime, UTC))
    except OSError as error:
        return Backup(folder, error=str(error))
    return Backup(folder)


@dataclass
class JobStatus:
    job: Job
    record: Record | None
    running: bool
    next_run: datetime | None
    stale: bool

    @property
    def failed(self) -> bool:
        return bool(self.record and self.record.result in FAILURES)

    def problem(self) -> str | None:
        name = self.job.name
        if self.failed:
            assert self.record
            how = HOW.get(self.record.result or "", "failed")
            return f"job {name}: its last run {how} (exit {self.record.exit_code})"
        if self.stale:
            return f"job {name}: no success in its last two runs"
        return None


@dataclass
class Report:
    at: datetime
    jobs: list[JobStatus]
    backup: Backup
    error: str | None = None  # the records could not be read
    problems: list[str] = field(default_factory=list)


def _stale(job: Job, record: Record | None, at: datetime) -> bool:
    if record is None:
        return False
    since = record.ok_at or record.seen_at
    ended = at - timedelta(seconds=job.timeout)
    due = list(itertools.islice(job.cron.times(ended, job.zone, back=True), 2))
    return len(due) == 2 and since < due[1]


def _running(name: str, record: Record | None) -> bool:
    found = held(lock_path(name))
    if found is not None:
        return found
    # No /proc/locks: from the records, which a killed pod may have left "running"
    return bool(
        record
        and record.started_at
        and (record.finished_at is None or record.started_at > record.finished_at)
    )


def collect(
    jobs: list[Job], db: Path | None, backups: Path | None, at: datetime | None = None
) -> Report:
    at = at or datetime.now(UTC)
    records: dict[str, Record] = {}
    error = None
    if db is None:
        error = "no database (SCRAP_DB_PATH)"
    else:
        try:
            records = read(db)
        except Exception as failure:  # noqa: BLE001  reported, as a problem
            error = f"cannot read the records in {db}: {failure}"
    statuses = [
        JobStatus(
            job,
            records.get(job.name),
            _running(job.name, records.get(job.name)),
            next(job.cron.times(at, job.zone), None),
            _stale(job, records.get(job.name), at),
        )
        for job in jobs
    ]
    report = Report(at, statuses, newest_backup(backups), error)
    report.problems = [p for s in statuses if (p := s.problem())]
    if error:
        report.problems.append(error)
    if problem := report.backup.problem(at):
        report.problems.append(problem)
    return report


def _when(at: datetime | None) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%d %H:%M") if at else "-"


def _iso(at: datetime | None) -> str | None:
    return at.astimezone(UTC).isoformat() if at else None


def _ago(since: datetime, at: datetime) -> str:
    hours = (at - since) / timedelta(hours=1)
    return f"{hours:.1f} h ago" if hours < 48 else f"{hours / 24:.1f} days ago"


def text(report: Report) -> str:
    """The report for a person, times in UTC."""
    rows = [["JOB", "SCHEDULE", "LAST RESULT", "LAST START", "LAST END", "LAST OK"]]
    rows[0] += ["NEXT RUN", "NOTE"]
    for status in report.jobs:
        job, record = status.job, status.record
        result = "-"
        if record and record.result:
            result = record.result
            if record.exit_code:
                result += f" ({record.exit_code})"
        notes = ["running"] if status.running else []
        notes += ["STALE"] if status.stale else []
        notes += ["never run"] if not (record and record.started_at) else []
        zone = job.zone.key if job.zone else "UTC"
        rows.append(
            [
                job.name,
                f"{job.cron.text} {zone}",
                result,
                _when(record and record.started_at),
                _when(record and record.finished_at),
                _when(record and record.ok_at),
                _when(status.next_run),
                ", ".join(notes),
            ]
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = [
        "  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip()
        for r in rows
    ]
    if not report.jobs:
        lines.append("(no jobs in SCRAP_SCHEDULE)")
    backup = report.backup
    if backup.folder is None:
        lines.append("Backups: not visible here (no SCRAP_BACKUPS)")
    elif backup.at and backup.run:
        lines.append(
            f"Backups: newest COMPLETE run {backup.run}, marked {_when(backup.at)}"
            f" ({_ago(backup.at, report.at)})"
        )
    lines.append(f"Times are UTC; now {_when(report.at)}.")
    if report.problems:
        lines += ["Problems:", *(f"- {p}" for p in report.problems)]
    else:
        lines.append("All healthy.")
    return "\n".join(lines)


def as_json(report: Report) -> dict[str, Any]:
    jobs = []
    for status in report.jobs:
        record = status.record
        jobs.append(
            {
                "name": status.job.name,
                "schedule": status.job.cron.text,
                "time_zone": status.job.zone.key if status.job.zone else "UTC",
                "running": status.running,
                "last_start": _iso(record and record.started_at),
                "last_end": _iso(record and record.finished_at),
                "last_result": record and record.result,
                "last_exit_code": record and record.exit_code,
                "last_success": _iso(record and record.ok_at),
                "known_since": _iso(record and record.seen_at),
                "next_run": _iso(status.next_run),
                "failed": status.failed,
                "stale": status.stale,
            }
        )
    backup = report.backup
    return {
        "at": _iso(report.at),
        "healthy": not report.problems,
        "problems": report.problems,
        "jobs": jobs,
        "backup": {
            "visible": backup.folder is not None,
            "folder": str(backup.folder) if backup.folder else None,
            "run": backup.run,
            "complete_at": _iso(backup.at),
            "error": backup.error,
        },
    }


def paths_from_env() -> tuple[Path, Path | None]:
    """The database and the backup folder, as the jobs container has them."""
    db = os.environ.get("SCRAP_DB_PATH")
    data = Path(os.environ.get("SCRAP_DATA_DIR", "data"))
    backups = os.environ.get("SCRAP_BACKUPS")
    return Path(db) if db else data / "scrap.db", Path(backups) if backups else None


def from_env(as_json_: bool = False) -> int:
    """scrap schedule status: print the report; 1 if there is a problem."""
    db, backups = paths_from_env()
    report = collect(load(os.environ.get("SCRAP_SCHEDULE", "[]")), db, backups)
    print(json.dumps(as_json(report), indent=2) if as_json_ else text(report))
    return 1 if report.problems else 0
