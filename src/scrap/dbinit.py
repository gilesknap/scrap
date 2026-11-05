"""Put the database in place before scrap starts, with Litestream (ADR 46).

The database lives on an emptyDir; the replica and everything else on the data volume.
The pod's init container runs this, and the first of these rules that applies decides:

1. A database on the emptyDir is kept (the pod restarted on its node). Never
   overwritten.
2. A restore staged by `scrap restore --stage` is taken up, and the replica set aside.
3. A replica: restored. If that fails, this fails: it never starts empty.
4. No replica, but a database in the data folder (an install from before Litestream):
   brought across with SQLite's backup API, and left where it is.
5. Neither: a new database, if nothing says there should be one.

What says there should be one: the state file (written on the data volume the first time
a database is put in place, so a volume that has held a replica cannot quietly look
new), files in files/, or backup runs (which live apart from the data volume, so they
notice a new, empty one). Then this fails, unless SCRAP_DB_INIT_OVERRIDE is on: a person
has looked.

Any error looking at the volume also fails. Nothing here treats "cannot tell" as "none":
so _present, not Path.exists(), which since Python 3.12 answers False on a stale mount.
"""

import json
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .backup import _snapshot
from .replica import ReplicaError, check_db, has_replica, restore_replica
from .store import Store, migrate

__all__ = ["InitError", "Paths", "check_restore", "from_env", "put_in_place", "staged"]

STATE = ".scrap-db-state.json"  # in the data folder
STAGED = "scrap.db.restored"  # in the data folder: from scrap restore --stage
LEGACY = "scrap.db"  # in the data folder: where the database lived before
RUN = re.compile(r"\d{8}T\d{6}Z")  # a backup run's folder


class InitError(Exception):
    """The database cannot safely be put in place."""


@dataclass
class Paths:
    db: Path  # on the emptyDir
    data: Path  # the data folder, on its volume
    replica: Path
    backups: Path | None = None  # the backup folder, if this install has one
    override: bool = False  # a person has looked: start without the replica or history


def _present(path: Path) -> bool:
    """Whether path exists; any error but "no such file" is raised."""
    try:
        os.stat(path)
    except FileNotFoundError:
        return False
    return True


def _fingerprint(path: Path) -> dict[str, int] | None:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def _read_state(paths: Paths) -> dict | None:
    try:
        return json.loads((paths.data / STATE).read_text())
    except FileNotFoundError:
        return None
    except ValueError as error:
        raise InitError(f"{paths.data / STATE} is not readable: {error}") from None


def _write_state(paths: Paths, how: str) -> None:
    state = {
        "how": how,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "legacy": _fingerprint(paths.data / LEGACY),
    }
    part = paths.data / f"{STATE}.part"
    with open(part, "w") as out:
        json.dump(state, out)
        out.flush()
        os.fsync(out.fileno())
    part.replace(paths.data / STATE)


def _clear(db: Path) -> None:
    """What a failed start may have left beside the database. Litestream's own notes go
    too: they describe a database that is not coming back."""
    for suffix in (
        "-wal",
        "-shm",
        ".lock",
        ".init",
        ".init-wal",
        ".init-shm",
        ".init.lock",
    ):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    shutil.rmtree(db.with_name(f".{db.name}-litestream"), ignore_errors=True)
    shutil.rmtree(db.with_name(f"{db.name}.restoring"), ignore_errors=True)


def _history(paths: Paths) -> list[str]:
    """Why this install should already have a database, if it should."""
    found = []
    try:
        if os.listdir(paths.data / "files"):
            found.append(f"files in {paths.data / 'files'}")
    except FileNotFoundError:
        pass
    if paths.backups:
        folders = [paths.backups, paths.backups / "monthly"]
        for folder in folders:
            try:
                runs = [name for name in os.listdir(folder) if RUN.fullmatch(name)]
            except FileNotFoundError:
                continue
            if runs:
                found.append(f"backup runs in {folder}, such as {max(runs)}")
    return found


def _restored(paths: Paths, how: str) -> str:
    """The replica, restored into a folder beside the database, then moved in."""
    folder = paths.db.with_name(f"{paths.db.name}.restoring")
    folder.mkdir()
    restore_replica(paths.replica, folder / "scrap.db")
    (folder / "scrap.db").replace(paths.db)
    shutil.rmtree(folder)
    _write_state(paths, how)
    return f"restored {paths.db} from the replica at {paths.replica}"


def _copied(src: Path, part: Path) -> None:
    """src into part with the backup API (src may have a WAL), checked."""
    _snapshot(src, part)
    check_db(part)


def _from_legacy(paths: Paths) -> str:
    legacy = paths.data / LEGACY
    part = Path(f"{paths.db}.init")
    _copied(legacy, part)
    part.replace(paths.db)
    _write_state(paths, "legacy")  # after the copy, which may checkpoint the old file
    return f"brought {legacy} across to {paths.db}, and left it there"


def _from_staged(paths: Paths) -> str:
    """A backup someone chose wins over the replica, which is set aside, not deleted."""
    part = Path(f"{paths.db}.init")
    _copied(paths.data / STAGED, part)
    retired = None
    if _present(paths.replica):
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        retired = paths.replica.with_name(f"{paths.replica.name}.retired-{stamp}")
        paths.replica.rename(retired)
    part.replace(paths.db)
    _write_state(paths, "staged restore")
    (paths.data / STAGED).unlink()
    aside = f"; the old replica is now {retired}" if retired else ""
    return f"took up the staged restore into {paths.db}{aside}"


def _fresh(paths: Paths) -> str:
    part = Path(f"{paths.db}.init")
    migrate(part)
    Path(f"{part}.lock").unlink()
    part.replace(paths.db)
    _write_state(paths, "new")
    return f"made a new database at {paths.db}"


def put_in_place(paths: Paths) -> str:
    """The rules at the top of this module. What it did, or InitError."""
    staged_file = paths.data / STAGED
    if _present(paths.db):
        if _present(staged_file):
            raise InitError(
                f"a restore is staged at {staged_file}, but this pod still has a live"
                f" database at {paths.db}. Scale scrap to 0, then back to 1"
            )
        return f"kept the database already at {paths.db}"
    paths.db.parent.mkdir(parents=True, exist_ok=True)
    _clear(paths.db)
    if _present(staged_file):
        return _from_staged(paths)
    state = _read_state(paths)
    legacy = _fingerprint(paths.data / LEGACY)
    if has_replica(paths.replica):
        if not paths.override:
            _refuse_changed_legacy(paths, state, legacy)
        return _restored(paths, state["how"] if state else "replica")
    if state and not paths.override:
        raise InitError(
            f"{paths.data / STATE} says a database was put in place on"
            f" {state.get('at')} ({state.get('how')}), but there is no replica at"
            f" {paths.replica}: it was lost, or this is not the volume it was on."
            " Restore a backup (docs/how-to/deploy-kubernetes.md), or if the pod died"
            " before Litestream's first write, set litestream.init.override to start"
            " from what is here"
        )
    if legacy:
        return _from_legacy(paths)
    history = _history(paths)
    if history and not paths.override:
        raise InitError(
            f"no database and no replica, but this install has been used: "
            f"{'; '.join(history)}. The volume may be the wrong one, or empty for a bad"
            " reason. Restore a backup (docs/how-to/deploy-kubernetes.md), or set"
            " litestream.init.override to start empty"
        )
    return _fresh(paths)


def _refuse_changed_legacy(
    paths: Paths, state: dict | None, legacy: dict[str, int] | None
) -> None:
    """The replica would win, silently undoing whoever just wrote scrap.db there: most
    likely a plain `scrap restore`, from before Litestream's restore steps."""
    legacy_file = paths.data / LEGACY
    if legacy and (not state or state.get("legacy") != legacy):
        raise InitError(
            f"{legacy_file} has changed since the replica at {paths.replica} began, so"
            " the replica would overwrite it. If it is a restore you meant to keep,"
            f" rename it to {STAGED} and start again; if not, rename it away"
        )


def from_env() -> str:
    """The init container: settings from the environment; a refusal stops the pod."""
    try:
        paths = Paths(
            db=Path(os.environ["SCRAP_DB_PATH"]),
            data=Path(os.environ["SCRAP_DATA_DIR"]),
            replica=Path(os.environ["SCRAP_LITESTREAM_REPLICA"]),
            backups=Path(b) if (b := os.environ.get("SCRAP_BACKUPS")) else None,
            override=os.environ.get("SCRAP_DB_INIT_OVERRIDE", "") == "on",
        )
    except KeyError as error:
        raise SystemExit(f"scrap db-init: {error.args[0]} is not set") from None
    try:
        return put_in_place(paths)
    except (InitError, ReplicaError, OSError, sqlite3.Error, RuntimeError) as error:
        raise SystemExit(f"scrap db-init: {error}") from None


def check_restore() -> None:
    """A plain scrap restore beside a replica would be undone by the next pod start."""
    if os.environ.get("SCRAP_LITESTREAM_REPLICA"):
        raise SystemExit(
            "scrap restore: this install replicates with Litestream, so use"
            " scrap restore --stage in the one-off restore pod, with scrap stopped"
            " (docs/how-to/deploy-kubernetes.md)"
        )


def staged(data_dir: Path) -> Store:
    """The Store a staged restore writes: scrap restore's usual path into the data
    folder, its database under the staged name for the next pod start to take up."""
    return Store(data_dir, data_dir / STAGED)
