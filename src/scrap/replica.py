"""The Litestream replica, as scrap uses it (ADR 46): whether there is one, a restore
of it into a checked file, its heartbeat, and a backup made from it.

The replica is Litestream's own directory of LTX files. scrap never reads the format:
only "has it any files?" and the `litestream restore` command.
"""

import os
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path

from .backup import backup
from .store import Store, connect, schema_version

__all__ = [
    "ReplicaError",
    "backup_from_replica",
    "beat",
    "binary",
    "check_db",
    "has_replica",
    "heartbeat_age_hours",
    "restore_replica",
]


class ReplicaError(Exception):
    """The replica, or a database made from it, cannot be used."""


def binary() -> str:
    """The litestream program: copied into the pod by an init container (the chart)."""
    return os.environ.get("SCRAP_LITESTREAM_BIN", "litestream")


def has_replica(replica: Path) -> bool:
    """True if the replica holds any file. Directories alone are not a replica:
    Litestream makes those before its first write. An error reading it is raised, never
    "none"."""

    def onerror(error: OSError) -> None:
        if not isinstance(error, FileNotFoundError):
            raise error

    return any(names for _, _, names in os.walk(replica, onerror=onerror))


def check_db(db: Path) -> None:
    """Refuse a database SQLite finds damaged, or from a newer scrap (read-only)."""
    uri = f"{db.resolve().as_uri()}?immutable=1"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise ReplicaError(f"{db}: integrity_check: {check}")
        schema_version(db)
    except (sqlite3.DatabaseError, RuntimeError) as error:
        raise ReplicaError(f"{db}: {error}") from error


def restore_replica(replica: Path, out: Path) -> None:
    """`litestream restore` of the replica into out (which must not exist), checked. No
    -if-replica-exists: a replica that cannot be restored is a failure, never "empty".
    """
    done = subprocess.run(
        [binary(), "restore", "-o", str(out), f"file://{replica}"], check=False
    )
    if done.returncode:
        raise ReplicaError(
            f"litestream restore of {replica} failed (exit {done.returncode})"
        )
    if not out.is_file():
        raise ReplicaError(f"litestream restore of {replica} made no database")
    check_db(out)


def beat(db: Path) -> None:
    """Stamp the database with the time, in minutes. The stamp is a write like any
    other, so a restore of the replica shows when replication last worked, even if
    nothing else was written since. The header's application_id holds it: nothing else
    uses that, and it needs no schema change."""
    with closing(connect(db)) as conn:
        conn.execute(f"PRAGMA application_id = {int(time.time() // 60)}")


def heartbeat_age_hours(db: Path) -> float | None:
    """Hours since the stamp in db (a closed copy), None if it has none."""
    uri = f"{db.resolve().as_uri()}?immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        stamp = conn.execute("PRAGMA application_id").fetchone()[0]
    return (time.time() / 60 - stamp) / 60 if stamp else None


def backup_from_replica(
    data_dir: Path, replica: Path, dest: Path, max_age_hours: float = 3.0
) -> None:
    """scrap backup, of a restore of the replica rather than the live database, with
    the data folder's files. The restore is at or behind the live database, and blobs
    are written before the transaction that records them, so the files it names are
    there; only a gc in the second or so of lag could differ, and gc and backups share a
    lock and run an hour apart. A stale replica is refused: gc trusts a COMPLETE run."""
    try:
        if not has_replica(replica):
            raise ReplicaError(f"no replica at {replica}")
        with tempfile.TemporaryDirectory(prefix="scrap-replica-") as folder:
            restored = Path(folder) / "scrap.db"
            restore_replica(replica, restored)
            age = heartbeat_age_hours(restored)
            if max_age_hours and (age is None or age > max_age_hours):
                seen = (
                    "no heartbeat" if age is None else f"a {age:.1f} hour old heartbeat"
                )
                raise ReplicaError(
                    f"the replica at {replica} is stale: {seen} (limit {max_age_hours}"
                    " hours); see Litestream's log in the scrap pod"
                )
            backup(Store(data_dir, restored), dest)
    except (ReplicaError, OSError) as error:
        raise SystemExit(f"scrap backup: {error}") from None
