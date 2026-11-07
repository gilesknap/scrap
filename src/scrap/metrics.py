"""Prometheus metrics for scrap schedule's jobs and the backups (#558): the same report
as scrap schedule status, served as text by the scheduler itself on SCRAP_METRICS_PORT
(GET /metrics), with no new dependency. Off while that is unset. Each scrape reads the
records afresh, so a run of scrap schedule --run shows too; a failed read is a 500.

Per job (label job): scrap_job_running; scrap_job_last_start_timestamp_seconds,
scrap_job_last_finish_timestamp_seconds and scrap_job_last_success_timestamp_seconds
(each absent until there is one); scrap_job_last_exit_code; scrap_job_last_result, 1 for
the last run's result (label result: ok, failed, deadline, not-started, paused, stopped)
and 0 for the others; scrap_job_failed (the last result is failed, deadline or
not-started); scrap_job_stale (no success in its last two runs, as scrap schedule status
says); scrap_job_next_run_timestamp_seconds. Then scrap_backup_visible,
scrap_backup_last_complete_timestamp_seconds (if a COMPLETE run is in view),
scrap_schedule_records_readable and scrap_schedule_problems (scrap schedule status's
count; 0 is healthy).
"""

import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .schedule import Job
from .schedule_record import FAILURES, RESULTS
from .schedule_status import Report, collect, paths_from_env

__all__ = ["from_env", "render", "serve"]

log = logging.getLogger("scrap.schedule")

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class _Out:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def metric(self, name: str, help_: str, samples: list[tuple[dict, float]]) -> None:
        self.lines += [f"# HELP {name} {help_}", f"# TYPE {name} gauge"]
        for labels, value in samples:
            inner = ",".join(f'{k}="{_label(v)}"' for k, v in labels.items())
            self.lines.append(
                f"{name}{{{inner}}} {value!r}" if inner else f"{name} {value!r}"
            )


def _stamp(at: datetime | None) -> float | None:
    return at.timestamp() if at else None


def render(report: Report) -> str:
    out = _Out()

    def per_job(name: str, help_: str, value: Callable) -> None:
        samples = [
            ({"job": s.job.name}, v) for s in report.jobs if (v := value(s)) is not None
        ]
        out.metric(name, help_, samples)

    def record(s, field: str) -> float | None:
        return _stamp(getattr(s.record, field)) if s.record else None

    per_job("scrap_job_running", "1 while the job runs.", lambda s: float(s.running))
    per_job(
        "scrap_job_last_start_timestamp_seconds",
        "When the job last started.",
        lambda s: record(s, "started_at"),
    )
    per_job(
        "scrap_job_last_finish_timestamp_seconds",
        "When the job's last run ended.",
        lambda s: record(s, "finished_at"),
    )
    per_job(
        "scrap_job_last_success_timestamp_seconds",
        "When a run of the job last ended with success.",
        lambda s: record(s, "ok_at"),
    )
    per_job(
        "scrap_job_last_exit_code",
        "The exit status of the job's last run.",
        lambda s: s.record.exit_code if s.record else None,
    )
    out.metric(
        "scrap_job_last_result",
        "1 for how the job's last run ended, 0 for the other results.",
        [
            ({"job": s.job.name, "result": r}, float(s.record.result == r))
            for s in report.jobs
            if s.record and s.record.result
            for r in RESULTS
        ],
    )
    per_job(
        "scrap_job_failed",
        f"1 if the job's last run ended {', '.join(FAILURES)}.",
        lambda s: float(s.failed),
    )
    per_job(
        "scrap_job_stale",
        "1 if neither of the job's last two runs due to have ended succeeded.",
        lambda s: float(s.stale),
    )
    per_job(
        "scrap_job_next_run_timestamp_seconds",
        "When the job is next due.",
        lambda s: _stamp(s.next_run),
    )
    backup = report.backup
    out.metric(
        "scrap_backup_visible",
        "1 if the backup folder is in view of the scheduler.",
        [({}, float(backup.folder is not None))],
    )
    complete = _stamp(backup.at)
    out.metric(
        "scrap_backup_last_complete_timestamp_seconds",
        "The COMPLETE marker's time on the newest backup run that has one.",
        [({}, complete)] if complete is not None else [],
    )
    out.metric(
        "scrap_schedule_records_readable",
        "1 if the jobs' records could be read from the database.",
        [({}, float(report.error is None))],
    )
    out.metric(
        "scrap_schedule_problems",
        "The problems scrap schedule status reports; 0 is healthy.",
        [({}, float(len(report.problems)))],
    )
    return "\n".join(out.lines) + "\n"


def serve(
    port: int, build: Callable[[], Report], host: str = ""
) -> ThreadingHTTPServer:
    """GET /metrics on port, from a daemon thread. Raises OSError if it cannot bind."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802  the stdlib's name
            if self.path.split("?")[0] != "/metrics":
                self.send_error(404)
                return
            try:
                body = render(build()).encode()
            except Exception:  # noqa: BLE001  a failed scrape, not a dead scheduler
                log.exception("metrics: could not make the report")
                self.send_error(500)
                return
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # a scrape every 30 s is not news

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def from_env(jobs: list[Job], db: Path | None) -> None:
    """Serve the metrics if SCRAP_METRICS_PORT is set. A bad port, or one that cannot
    be bound, is logged, and the scheduler runs without them."""
    port = os.environ.get("SCRAP_METRICS_PORT")
    if not port:
        return
    backups = paths_from_env()[1]
    try:
        serve(int(port), lambda: collect(jobs, db, backups))
    except (ValueError, OSError, OverflowError) as error:
        log.error("metrics: not served on port %s: %s", port, error)
        return
    log.info("metrics: on port %s, at /metrics", port)
