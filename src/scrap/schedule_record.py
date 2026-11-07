"""What scrap schedule records of each job's runs (ADR 46, #558), in the database's
scheduled_job table, so it survives the pod: the emptyDir is restored from the replica.

The writes are the scheduler's (and scrap schedule --run's); a failed one is logged and
never stops a job or the scheduler. The reads are scrap schedule status's and the
metrics', and raise.
"""

import logging
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .store import connect, now

__all__ = [
    "DEADLINE",
    "FAILED",
    "FAILURES",
    "NOT_STARTED",
    "OK",
    "PAUSED",
    "RESULTS",
    "STOPPED",
    "Record",
    "finished",
    "held",
    "lock_path",
    "read",
    "seen",
    "started",
]

log = logging.getLogger("scrap.schedule")

OK = "ok"
FAILED = "failed"  # a non-zero exit
DEADLINE = "deadline"  # stopped at its deadline
NOT_STARTED = "not-started"  # could not be started
PAUSED = "paused"  # a Claude pass stopped at a queue pause or spent budget
STOPPED = "stopped"  # stopped with the pod (or scrap schedule --run told to stop)
RESULTS = (OK, FAILED, DEADLINE, NOT_STARTED, PAUSED, STOPPED)
FAILURES = (FAILED, DEADLINE, NOT_STARTED)


@dataclass
class Record:
    """A job's row: its times are aware UTC, None where it has none."""

    name: str
    seen_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: str | None = None
    exit_code: int | None = None
    ok_at: datetime | None = None


def lock_path(name: str) -> Path:
    """The job's lock, in /tmp: shared by the scheduler and scrap schedule --run."""
    return Path(tempfile.gettempdir()) / f"scrap-job-{name}.lock"


def held(path: Path, locks: Path = Path("/proc/locks")) -> bool | None:
    """Whether someone holds the flock on path, from the kernel's list (so without
    taking it, which could make the scheduler skip a run); None if it cannot tell."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    except OSError:
        return None
    try:
        text = locks.read_text()
    except OSError:
        return None
    # "1: FLOCK  ADVISORY  WRITE 1234 fd:01:5678 0 EOF"; a waiter's line has "->"
    file = f"{os.major(stat.st_dev):02x}:{os.minor(stat.st_dev):02x}:{stat.st_ino}"
    return any(
        "FLOCK" in parts and "->" not in parts and file in parts
        for parts in (line.split() for line in text.splitlines())
    )


_failing: set[str] = set()  # what has failed to record, logged once until it works


def _write(db: Path | None, key: str, what: str, sql: str, *args: object) -> bool:
    """The write; False if it failed. A failure is logged once for key (a job, or the
    list of jobs), as a warning, until a write for key works again: a database below
    this table's migration would otherwise log each minute."""
    if not db:
        return False
    try:
        with closing(connect(db)) as conn:
            conn.execute(sql, args)
    except Exception as error:  # noqa: BLE001  a lost record must never stop a job
        if key not in _failing:
            _failing.add(key)
            log.warning("could not record %s (quiet until it works): %s", what, error)
        return False
    if key in _failing:
        _failing.discard(key)
        log.info("recording %s works again", what)
    return True


def seen(db: Path | None, names: list[str]) -> bool:
    """Each job known from now, unless it already is; False if it could not say."""
    if not names:
        return True
    at = now()
    rows = ", ".join("(?, ?)" for _ in names)
    pairs = [value for name in names for value in (name, at)]
    return _write(
        db,
        "",
        "the jobs",
        f"INSERT INTO scheduled_job (name, seen_at) VALUES {rows}"
        " ON CONFLICT (name) DO NOTHING",
        *pairs,
    )


def started(db: Path | None, name: str) -> None:
    at = now()
    _write(
        db,
        name,
        f"job {name}'s start",
        "INSERT INTO scheduled_job (name, seen_at, started_at) VALUES (?, ?, ?)"
        " ON CONFLICT (name) DO UPDATE SET started_at = excluded.started_at",
        name,
        at,
        at,
    )


def finished(db: Path | None, name: str, result: str, code: int | None) -> None:
    at = now()
    ok_at = at if result == OK else None
    _write(
        db,
        name,
        f"job {name}'s end",
        "INSERT INTO scheduled_job"
        " (name, seen_at, finished_at, result, exit_code, ok_at)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (name) DO UPDATE SET finished_at = excluded.finished_at,"
        " result = excluded.result, exit_code = excluded.exit_code,"
        " ok_at = coalesce(excluded.ok_at, ok_at)",
        name,
        at,
        at,
        result,
        code,
        ok_at,
    )


def _time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def read(db: Path) -> dict[str, Record]:
    """Every job's row, read only (a missing database raises, not made)."""
    uri = f"{db.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.execute("PRAGMA busy_timeout = 5000")
        rows = conn.execute(
            "SELECT name, seen_at, started_at, finished_at, result, exit_code, ok_at"
            " FROM scheduled_job"
        ).fetchall()
    return {
        name: Record(
            name,
            datetime.fromisoformat(seen),
            _time(start),
            _time(end),
            result,
            code,
            _time(ok),
        )  # fmt: skip
        for name, seen, start, end, result, code, ok in rows
    }
