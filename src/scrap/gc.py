"""``scrap gc``: delete the stored files nothing uses any more.

A file (a blob: ``files/ab/<sha256>`` and its ``blob`` row) is in use while any of these
refers to it:

- a page's text, the trash's too (so a page brought back has its images), by its
  address ``/api/blobs/<sha>`` (see :func:`body_refs`);
- a capture (``capture_blob``);
- a derived row, or an ingest job, of a photo (``source_sha256``);
- a model run: the photo it was about and the JPEG it sent (``sent_sha256``).

Files younger than the grace period are kept whatever refers to them: a capture writes
its files before the transaction that records them, so a file being uploaded right now
is referred to by nothing yet. ``Store.put_blob`` touches a file it finds already there,
so re-uploading old bytes makes them young again too.

Deleting is safe while scrap serves. The references are read again inside a write
transaction (no capture, edit or ingest can commit meanwhile), and each file is first
renamed aside and its age checked once more: an upload that touched it before the
rename puts it back, one after it finds no file and writes its own. A run that stops
between the rename and putting a file back leaves it aside: each run first puts back
any file left aside whose name is free. If the references cannot be read, nothing is
deleted. Old page revisions are not references: only each page's current text is read.
Model runs are pruned too (see :func:`scrap.retention.prune_runs`): ``model_run`` and
``enrich_run`` rows hold the stored prompts and responses and would otherwise grow for
ever. A run is kept while anything refers to it, while it is the latest for its page
(or photo), and while it is younger than ``RUN_DAYS``. Deleting a ``model_run`` frees
the JPEG it sent, which the same run then finds unused. ``topic_run`` rows (one a
week) are not pruned.

Files of captures are not deleted while their page lasts: one no page shows any more (an
orphan) is gathered onto the month's review page instead, with --delete (see
:mod:`scrap.orphans`, #124), and is let go only when that review page is purged.

Retention (:mod:`scrap.retention`, #276): a page in the trash more than ``trash_days``
(None: never) is purged, with its captures and all that hangs on them, and finished job
rows past ``job_days`` and runs past ``run_days`` are deleted, in a transaction of their
own committed before the references are read. So no file is unlinked while that is
uncommitted, and the purged pages' files go in the same run (old enough, and only after
a recent backup, as any unused file). A dry run does the same in a transaction it rolls
back, so it reports them and the files they would free, and changes nothing.

Backups are untouched: each backup run holds its own copy of every file its database
refers to.
"""

import fcntl
import logging
import os
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import orphans, retention
from .retention import RUN_DAYS, prune_runs
from .store import (
    SHA256,
    ConflictError,
    InvalidError,
    Store,
    body_refs,
    schema_version,
    transaction,
)

__all__ = [
    "GRACE_HOURS",
    "JOB_DAYS",
    "RUN_DAYS",
    "TRASH_DAYS",
    "GcError",
    "Report",
    "body_refs",
    "collect",
    "in_use",
    "prune_runs",
]

log = logging.getLogger(__name__)

GRACE_HOURS = 24.0
TRASH_DAYS = retention.TRASH_DAYS
JOB_DAYS = retention.JOB_DAYS
TEMP = ".up-"  # put_blob's temporary files: one left over is a crashed upload
LOCK = "gc.lock"  # in the data folder, held by a run that deletes
ASIDE = ".gc-"  # a file being deleted


class GcError(Exception):
    """The references could not be read: nothing was deleted."""


# Every column that holds a file's SHA-256 a row needs (NULLs are left out)
COLUMNS = (
    "SELECT sha256 FROM capture_blob",
    "SELECT source_sha256 FROM derived",
    "SELECT source_sha256 FROM job",
    "SELECT source_sha256 FROM model_run",
    "SELECT sent_sha256 FROM model_run WHERE sent_sha256 IS NOT NULL",
)


def in_use(conn: sqlite3.Connection) -> set[str]:
    """Every file something refers to, read on conn (in its transaction, if open)."""
    used: set[str] = set()
    for sql in COLUMNS:
        used.update(row[0] for row in conn.execute(sql))
    for (body,) in conn.execute("SELECT body FROM page"):  # deleted_at too: the trash
        used |= body_refs(body)
    return used


@dataclass
class Report:
    """What a run found (and deleted): counts and sizes only, never any page text."""

    unused: int = 0  # files nothing refers to, older than the grace period
    unused_bytes: int = 0
    rows: int = 0  # blob rows nothing refers to (with or without a file)
    temp: int = 0  # leftover upload temporaries
    temp_bytes: int = 0
    young: int = 0  # unused, but inside the grace period: kept
    kept: int = 0  # unused when looked at, in use (or touched) when deleting: kept
    restored: int = 0  # left aside by a run that stopped mid-delete: put back
    model_runs: int = 0  # model_run rows past retention (deleted, with --delete)
    enrich_runs: int = 0  # enrich_run rows past retention
    orphans: int = 0  # capture files no page shows: gathered (with --delete)
    purged: int = 0  # pages in the trash past retention: purged (with --delete)
    let_go: int = 0  # orphaned files a purged review page showed: let go with it
    jobs: int = 0  # finished ingest job rows past retention
    enrich_jobs: int = 0  # finished enrich job rows past retention
    trash_days: float | None = TRASH_DAYS  # None: the trash is never purged
    job_days: float = JOB_DAYS
    orphan_title: str = ""  # the month's review page they go on
    deleted: bool = False
    shas: list[str] = field(default_factory=list)  # for tests; not printed

    def text(self) -> str:
        mb = (self.unused_bytes + self.temp_bytes) / 2**20
        what = "deleted" if self.deleted else "would delete (dry run: --delete deletes)"
        return (
            f"scrap gc: {what} {self.unused} unused files and {self.temp} leftover"
            f" uploads, {mb:.1f} MB; {self.rows} unused file records; kept"
            f" {self.young} unused files younger than the grace period"
            + (f" and {self.kept} used again meanwhile" if self.kept else "")
            + f"; {self.model_runs} model runs and {self.enrich_runs} enrich runs"
            f" older than the retention"
            + f"; {'gathered' if self.deleted else 'would gather'} {self.orphans}"
            f" orphaned files onto {self.orphan_title}"
            + (
                f"; {'purged' if self.deleted else 'would purge'} {self.purged} pages"
                f" in the trash more than {self.trash_days:g} days"
                if self.trash_days is not None
                else "; the trash is never purged (--trash-days off)"
            )
            + (f" (and {self.let_go} orphaned files)" if self.let_go else "")
            + f"; {self.jobs} ingest jobs and {self.enrich_jobs} enrich jobs finished"
            f" more than {self.job_days:g} days ago"
            + (
                f"; put back {self.restored} files an earlier run left aside"
                if self.restored
                else ""
            )
        )


def _files(store: Store) -> tuple[dict[str, Path], list[Path]]:
    """The stored files by SHA-256, and leftover upload temporaries; anything else
    in files/ is never touched."""
    blobs, temps = {}, []
    if not store.files.is_dir():
        raise GcError(f"no files folder at {store.files}")
    for entry in os.scandir(store.files):
        if entry.name.startswith(TEMP) and entry.is_file(follow_symlinks=False):
            temps.append(Path(entry.path))
        elif len(entry.name) == 2 and entry.is_dir(follow_symlinks=False):
            for sub in os.scandir(entry.path):
                ok = SHA256.fullmatch(sub.name) and sub.name[:2] == entry.name
                if ok and sub.is_file(follow_symlinks=False):
                    blobs[sub.name] = Path(sub.path)
    return blobs, temps


def _restore(store: Store) -> int:
    """Put back the files a run left aside (``.gc-<sha>``) when it stopped between the
    rename and the delete or relink: the next steps decide again whether they are used.
    One whose name is taken already has its bytes there (same SHA-256): the aside
    goes."""
    restored = 0
    for entry in os.scandir(store.files):
        if not (len(entry.name) == 2 and entry.is_dir(follow_symlinks=False)):
            continue
        for sub in os.scandir(entry.path):
            sha = sub.name.removeprefix(ASIDE)
            if sha == sub.name or not SHA256.fullmatch(sha) or sha[:2] != entry.name:
                continue
            if not sub.is_file(follow_symlinks=False):
                continue
            aside = Path(sub.path)
            try:
                os.link(aside, aside.with_name(sha))
                restored += 1
            except FileExistsError:
                pass
            except FileNotFoundError:
                continue  # another run finished with it meanwhile
            aside.unlink(missing_ok=True)
    return restored


def _old(path: Path, cutoff: float) -> bool | None:
    """Whether a file is older than cutoff (None: it is gone)."""
    try:
        return path.stat().st_mtime < cutoff
    except FileNotFoundError:
        return None


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _delete(store: Store, sha: str, path: Path, cutoff: float) -> bool:
    """Delete one unused file unless an upload touched it meanwhile."""
    aside = path.with_name(f"{ASIDE}{sha}")
    try:
        os.rename(path, aside)
    except FileNotFoundError:
        return True  # already gone
    if _old(aside, cutoff):  # nobody touched it before the rename: later ones relink
        aside.unlink(missing_ok=True)
        for size in (480, 2048):  # its previews: made again from nothing else
            cache = store.dir / "cache" / "previews" / str(size) / sha[:2]
            (cache / f"{sha}.jpg").unlink(missing_ok=True)
        return True
    try:  # an upload of the same bytes touched it: it stays
        os.link(aside, path)
    except FileExistsError:
        pass  # written again meanwhile: the same bytes
    except FileNotFoundError:
        pass  # another run put it back meanwhile
    aside.unlink(missing_ok=True)
    return False


def collect(
    store: Store,
    delete: bool = False,
    grace_hours: float = GRACE_HOURS,
    run_days: float = RUN_DAYS,
    _between: Iterable[None] = (),
    trash_days: float | None = TRASH_DAYS,
    job_days: float = JOB_DAYS,
) -> Report:
    """Find (and with delete, delete) the files nothing refers to, and purge the trash
    and the job records past retention; see the module.

    _between is for tests: each item is taken between the dry look and the delete.
    """
    if grace_hours < 0:
        raise GcError("the grace period must not be negative")
    # At least a day each (today's spend is summed from the runs), at most MAX_DAYS
    for days, what in ((run_days, "run"), (trash_days, "trash"), (job_days, "job")):
        try:
            if days is not None:
                retention.check_days(days, what)
        except ValueError as error:
            raise GcError(str(error)) from None
    report = Report(trash_days=trash_days, job_days=job_days)
    if not store.db.is_file():
        raise GcError(f"no database at {store.db}")
    if not delete:
        return _collect(store, False, grace_hours, run_days, _between, report)
    # One deleting run at a time: a run by hand cannot race the nightly one.
    try:
        lock = open(store.dir / LOCK, "w")  # noqa: SIM115 (closed when the run ends)
    except OSError as error:
        raise GcError(f"cannot take the lock {store.dir / LOCK}: {error}") from None
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GcError(
                f"another scrap gc is deleting (it holds {store.dir / LOCK});"
                " try again when it has finished"
            ) from None
        return _collect(store, True, grace_hours, run_days, _between, report)


def _gather(store: Store, report: Report, stamp: str) -> bool:
    """Gather the orphans onto the month's review page; whether that was done (not
    when the page was edited meanwhile: then no review page is purged this run, as
    what it holds may not be all gathered)."""
    try:
        report.orphans = orphans.gather(store, stamp, report.trash_days).count
    except ConflictError:  # edited meanwhile: the next run gathers them
        log.warning("scrap gc: the orphan page changed meanwhile; not gathered")
        return False
    except (InvalidError, sqlite3.Error) as error:
        raise GcError(
            f"cannot gather the orphaned files, so nothing was deleted: {error}"
        ) from None
    return True


def _retain(
    conn: sqlite3.Connection,
    report: Report,
    run_days: float,
    grace: str,
    delete: bool,
    review: bool,
) -> None:
    """Purge the trash (review pages only if review) and prune the job rows past
    retention, and the runs (counted only, unless delete), recording the counts in
    report. A dry run calls it too, in a transaction it rolls back."""
    if report.trash_days is not None:
        purged = retention.purge(
            conn, retention.stamp(report.trash_days), grace, review
        )
        report.purged, report.let_go = purged.pages, purged.files
    report.jobs, report.enrich_jobs = retention.prune_jobs(
        conn, retention.stamp(report.job_days), delete=True
    )
    report.model_runs, report.enrich_runs = prune_runs(conn, run_days, delete)


def _collect(
    store: Store,
    delete: bool,
    grace_hours: float,
    run_days: float,
    _between: Iterable[None],
    report: Report,
) -> Report:
    cutoff = time.time() - grace_hours * 3600
    stamp = datetime.fromtimestamp(cutoff, UTC).isoformat(timespec="milliseconds")
    stamp = stamp.replace("+00:00", "Z")
    report.orphan_title = orphans.TITLE.format(month=f"{orphans.clock():%Y-%m}")
    try:
        schema_version(store.db)  # refuses a database newer than this scrap
        if not store.files.is_dir():
            raise GcError(f"no files folder at {store.files}")
        try:
            report.restored = _restore(store)
        except OSError as error:
            raise GcError(
                f"cannot put back a file left aside by an earlier run, so nothing"
                f" was deleted: {error}"
            ) from None
        if delete:  # first, so a file gathered now is in use below
            review = _gather(store, report, stamp)
            # Retention commits on its own, before any file is looked at: a file is
            # only ever unlinked once what made it unused is committed.
            try:
                with store.connect() as conn, transaction(conn):
                    _retain(conn, report, run_days, stamp, True, review)
            except sqlite3.Error as error:
                raise GcError(
                    f"cannot purge the trash or prune old records, so nothing was"
                    f" deleted: {error}"
                ) from None
        with store.connect() as conn:
            # One consistent snapshot of every reference. A dry run sees them as
            # retention would leave them: purged and pruned here, then rolled back
            # (a write transaction, so the purge's writes cannot be refused).
            conn.execute("BEGIN" if delete else "BEGIN IMMEDIATE")
            try:
                if not delete:
                    report.orphans = len(orphans.find(conn, stamp))
                    _retain(conn, report, run_days, stamp, False, True)
                used = in_use(conn)
                rows = dict(conn.execute("SELECT sha256, created_at FROM blob"))
            finally:
                conn.execute("ROLLBACK")
        files, temps = _files(store)
    except (sqlite3.Error, OSError, RuntimeError) as error:
        raise GcError(
            f"cannot read what is in use, so nothing was deleted: {error}"
        ) from None

    def unused(shas: Iterable[str]) -> list[str]:
        return sorted(sha for sha in shas if sha not in used)

    candidates = unused(set(files) | set(rows))
    old: list[str] = []
    for sha in candidates:
        age = _old(files[sha], cutoff) if sha in files else None
        if age is False or (age is None and _young_row(rows[sha], cutoff)):
            report.young += 1
        else:
            old.append(sha)
    temps = [t for t in temps if _old(t, cutoff)]
    sizes = {sha: _size(files[sha]) for sha in old if sha in files}
    sizes |= {str(t): _size(t) for t in temps}
    for _ in _between:
        pass
    if not delete:
        _count(report, old, files, rows, temps, sizes)
        return report

    with store.connect() as conn:
        try:
            with transaction(conn):  # no capture, edit or ingest commits meanwhile
                used = in_use(conn)
                again = set(unused(old))
                report.kept = len(old) - len(again)
                gone: list[str] = []
                for sha in again:
                    if sha in files and not _delete(store, sha, files[sha], cutoff):
                        report.kept += 1
                        continue
                    gone.append(sha)
                conn.executemany(
                    "DELETE FROM blob WHERE sha256 = ?",
                    [(sha,) for sha in gone if sha in rows],
                )
        except sqlite3.Error as error:
            raise GcError(f"cannot delete: {error}") from None
    for temp in temps:
        temp.unlink(missing_ok=True)
    _count(report, gone, files, rows, temps, sizes)
    report.deleted = True
    return report


def _young_row(created_at: str, cutoff: float) -> bool:
    """A blob row with no file: young if recorded after cutoff."""
    try:
        return datetime.fromisoformat(created_at).timestamp() >= cutoff
    except ValueError:
        return True  # unreadable: keep it


def _count(
    report: Report,
    shas: list[str],
    files: dict[str, Path],
    rows: dict[str, str],
    temps: list[Path],
    sizes: dict[str, int],
) -> None:
    report.shas = sorted(shas)
    on_disk = [sha for sha in shas if sha in files]
    report.unused = len(on_disk)
    report.unused_bytes = sum(sizes[sha] for sha in on_disk)
    report.rows = sum(sha in rows for sha in shas)
    report.temp = len(temps)
    report.temp_bytes = sum(sizes[str(t)] for t in temps)
