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
Model runs are pruned too (see :func:`prune_runs`): ``model_run`` and ``enrich_run``
rows hold the stored prompts and responses and would otherwise grow for ever. A run is
kept while anything refers to it, while it is the latest for its page (or photo), and
while it is younger than ``RUN_DAYS``. Deleting a ``model_run`` frees the JPEG it sent,
which the next gc then finds unused.

Files of captures are never deleted: one no page shows any more (an orphan) is gathered
onto the month's review page instead, with --delete (see :mod:`scrap.orphans`, #124).

Backups are untouched: each backup run holds its own copy of every file its database
refers to.
"""

import fcntl
import os
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import orphans
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
    "RUN_DAYS",
    "GcError",
    "Report",
    "body_refs",
    "collect",
    "in_use",
    "prune_runs",
]

GRACE_HOURS = 24.0
RUN_DAYS = 30.0  # model_run / enrich_run rows younger than this are kept
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
                f"; put back {self.restored} files an earlier run left aside"
                if self.restored
                else ""
            )
        )


def _cutoff_stamp(run_days: float) -> str:
    when = datetime.now(UTC) - timedelta(days=run_days)
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def prune_runs(
    conn: sqlite3.Connection, run_days: float = RUN_DAYS, delete: bool = False
) -> tuple[int, int]:
    """Count (and with delete, delete) the model_run and enrich_run rows past retention.

    A row is kept while it is still running; or younger than run_days; or the newest
    for its page (``enrich_run``) or for its photo (``model_run``); or the newest ok
    ``related`` enrich_run of a page (``enrich --related`` reads it as "up to date",
    see ``enrich.STALE``); or something
    refers to it: ``enrichment.run_id``, ``writeup.run_id`` and ``derived.run_id`` (a
    superseded version too), or a kept ``model_run`` that continues it
    (``parent_id``). Returns the
    counts (model_run, enrich_run). Call inside the write transaction when deleting.
    """
    stamp = _cutoff_stamp(run_days)
    models = conn.execute(
        "SELECT id, parent_id, capture_id, source_sha256, started_at, status"
        " FROM model_run"
    ).fetchall()
    keep = {r[0] for r in models if r[5] == "running" or r[4] >= stamp}
    keep |= {
        row[0]
        for row in conn.execute("SELECT run_id FROM derived WHERE run_id IS NOT NULL")
    }
    newest: dict[tuple[str, str], int] = {}
    for row in models:
        key = (row[2], row[3])
        newest[key] = max(newest.get(key, 0), row[0])
    keep |= set(newest.values())
    parent = {r[0]: r[1] for r in models}
    for run in list(keep):  # a kept turn needs the turns before it
        while (run := parent.get(run)) is not None and run not in keep:
            keep.add(run)
    gone_models = sorted(r[0] for r in models if r[0] not in keep)

    enrich = conn.execute(
        "SELECT id, page_id, started_at, status FROM enrich_run"
    ).fetchall()
    keep_e = {r[0] for r in enrich if r[3] == "running" or r[2] >= stamp}
    keep_e |= {
        row[0]
        for row in conn.execute(
            "SELECT run_id FROM enrichment WHERE run_id IS NOT NULL"
            " UNION SELECT run_id FROM writeup WHERE run_id IS NOT NULL"
        )
    }
    latest: dict[str, int] = {}
    for row in enrich:
        latest[row[1]] = max(latest.get(row[1], 0), row[0])
    keep_e |= set(latest.values())
    # enrich --related treats a page as up to date by its newest ok related run
    # (enrich.STALE), so pruning that one would cost an extra Claude call.
    keep_e |= {
        row[0]
        for row in conn.execute(
            "SELECT MAX(id) FROM enrich_run WHERE status = 'ok'"
            " AND json_extract(request, '$.purpose') = 'related' GROUP BY page_id"
        )
    }
    gone_enrich = sorted(r[0] for r in enrich if r[0] not in keep_e)

    if delete:
        # Newest first: a turn is deleted before the one it continues.
        conn.executemany(
            "DELETE FROM model_run WHERE id = ?", [(i,) for i in reversed(gone_models)]
        )
        conn.executemany(
            "DELETE FROM enrich_run WHERE id = ?", [(i,) for i in gone_enrich]
        )
    return len(gone_models), len(gone_enrich)


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
) -> Report:
    """Find (and with delete, delete) the files nothing refers to; see the module.

    _between is for tests: each item is taken between the dry look and the delete.
    """
    if grace_hours < 0:
        raise GcError("the grace period must not be negative")
    if run_days < 1:  # today's spend is summed from the runs: keep at least a day
        raise GcError("the run retention must be at least 1 day")
    if not store.db.is_file():
        raise GcError(f"no database at {store.db}")
    if not delete:
        return _collect(store, False, grace_hours, run_days, _between)
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
        return _collect(store, True, grace_hours, run_days, _between)


def _collect(
    store: Store,
    delete: bool,
    grace_hours: float,
    run_days: float,
    _between: Iterable[None],
) -> Report:
    cutoff = time.time() - grace_hours * 3600
    stamp = datetime.fromtimestamp(cutoff, UTC).isoformat(timespec="milliseconds")
    stamp = stamp.replace("+00:00", "Z")
    report = Report(orphan_title=orphans.TITLE.format(month=f"{orphans.clock():%Y-%m}"))
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
            try:
                report.orphans = orphans.gather(store, stamp).count
            except (ConflictError, InvalidError, sqlite3.Error) as error:
                raise GcError(
                    f"cannot gather the orphaned files, so nothing was deleted: {error}"
                ) from None
        with store.connect() as conn:
            conn.execute("BEGIN")  # one consistent snapshot of every reference
            try:
                if not delete:
                    report.orphans = len(orphans.find(conn, stamp))
                used = in_use(conn)
                rows = dict(conn.execute("SELECT sha256, created_at FROM blob"))
                report.model_runs, report.enrich_runs = prune_runs(conn, run_days)
            finally:
                conn.execute("COMMIT")
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
                report.model_runs, report.enrich_runs = prune_runs(
                    conn, run_days, delete=True
                )
                used = in_use(conn)  # the runs just deleted no longer count
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
