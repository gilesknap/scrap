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
rename puts it back, one after it finds no file and writes its own. If the references
cannot be read, nothing is deleted. Backups are untouched: each backup run holds its own
copy of every file its database refers to.
"""

import os
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .store import SHA256, Store, body_refs, schema_version, transaction

__all__ = ["GRACE_HOURS", "GcError", "Report", "body_refs", "collect", "in_use"]

GRACE_HOURS = 24.0
TEMP = ".up-"  # put_blob's temporary files: one left over is a crashed upload
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
        aside.unlink()
        for size in (480, 2048):  # its previews: made again from nothing else
            cache = store.dir / "cache" / "previews" / str(size) / sha[:2]
            (cache / f"{sha}.jpg").unlink(missing_ok=True)
        return True
    try:  # an upload of the same bytes touched it: it stays
        os.link(aside, path)
    except FileExistsError:
        pass  # written again meanwhile: the same bytes
    aside.unlink()
    return False


def collect(
    store: Store,
    delete: bool = False,
    grace_hours: float = GRACE_HOURS,
    _between: Iterable[None] = (),
) -> Report:
    """Find (and with delete, delete) the files nothing refers to; see the module.

    _between is for tests: each item is taken between the dry look and the delete.
    """
    if grace_hours < 0:
        raise GcError("the grace period must not be negative")
    if not store.db.is_file():
        raise GcError(f"no database at {store.db}")
    cutoff = time.time() - grace_hours * 3600
    report = Report()
    try:
        schema_version(store.db)  # refuses a database newer than this scrap
        with store.connect() as conn:
            conn.execute("BEGIN")  # one consistent snapshot of every reference
            try:
                used = in_use(conn)
                rows = dict(conn.execute("SELECT sha256, created_at FROM blob"))
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
