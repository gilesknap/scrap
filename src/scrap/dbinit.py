"""Put the database in place before scrap starts, with Litestream (ADR 46).

The database lives on an emptyDir; the replica and everything else on the data volume.
The pod's init container runs this, and the first of these rules that applies decides:

1. A database on the emptyDir is kept (the pod restarted on its node). Never
   overwritten.
2. A restore staged by `scrap restore --stage` is taken up, and the replica set aside.
3. A replica: restored. If that fails, this fails: it never starts empty.
4. No replica, but a database with pages in the data folder (an install from before
   Litestream): brought across with SQLite's backup API, and left where it is.
5. Neither: a new database, if nothing says there should be one.

What says there should be one: the state file (written on the data volume the first time
a database is put in place, so a volume that has held a replica cannot quietly look
new), files in files/, or backup runs (which live apart from the data volume, so they
notice a new, empty one). Then this fails. So does a replica clearly behind the stamp
last written to the live database, which means replication had stalled, and a staged
restore older than the replica, which means scrap went on running after it.

SCRAP_DB_INIT_OVERRIDE goes past those: a person has looked. Using it is recorded in the
state file, and gc only counts until a person clears that (gc_guard.py). A source too
big for the emptyDir is refused regardless.

Any error looking at the volume also fails. Nothing here treats "cannot tell" as "none":
so _present, not Path.exists(), which since Python 3.12 answers False on a stale mount.
"""

import os
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .backup import RUN, _snapshot
from .dbstate import (
    HEALTH,
    LEGACY,
    STAGED,
    STATE,
    StateError,
    fingerprint,
    last_stamp,
    now_iso,
    parse_size,
    read_state,
    write_state,
)
from .replica import (
    ReplicaError,
    check_db,
    has_replica,
    newest_file,
    read_stamp,
    restore_replica,
)
from .schedule import load
from .store import Store, connect, migrate

__all__ = ["InitError", "Paths", "check_restore", "from_env", "put_in_place", "staged"]

# How far behind the last stamp a restored replica may be: a stamp a little out of date
# is the last write of a dying node; two is replication that had stopped.
BEHIND_MINUTES = 30


class InitError(Exception):
    """The database cannot safely be put in place."""


@dataclass
class Paths:
    db: Path  # on the emptyDir
    data: Path  # the data folder, on its volume
    replica: Path
    backups: Path | None = None  # the backup folder, if this install has one
    override: bool = False  # a person has looked: start without the replica or history
    size_limit: int | None = None  # the emptyDir's, in bytes
    overridden: list[str] = field(default_factory=list)  # refusals override got past
    notes: list[str] = field(default_factory=list)  # warnings for the log


def _refuse(paths: Paths, message: str) -> None:
    """Stop, unless a person said to go on: then it is remembered."""
    if not paths.override:
        raise InitError(message)
    paths.overridden.append(message)


def _present(path: Path) -> bool:
    """Whether path exists; any error but "no such file" is raised."""
    try:
        os.stat(path)
    except FileNotFoundError:
        return False
    return True


def _too_big(paths: Paths, size: int, what: str) -> None:
    """Over half the emptyDir: its WAL and Litestream's own LTX share the space, and
    past the limit the kubelet evicts the pod, again on every start."""
    if paths.size_limit and size * 2 > paths.size_limit:
        raise InitError(
            f"{what} is {size // 10**6} MB, over half of the database's emptyDir"
            f" ({paths.size_limit // 10**6} MB): raise litestream.sizeLimit"
        )


def _placed(paths: Paths, how: str | None, **fields: object) -> None:
    """The database is in place: note how, and any override used."""
    if paths.overridden:
        fields |= {
            "override_at": now_iso(),
            "override_why": "; ".join(m[:200] for m in paths.overridden),
        }
    write_state(paths.data, how, **fields)
    (paths.data / HEALTH).unlink(missing_ok=True)  # the next stamp begins again


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


def _check_stamp(paths: Paths, db: Path) -> None:
    """How old the restored replica is, against the stamp last written to the live one.
    A stamp behind is writes that never reached it: replication had stalled, or the last
    sync at shutdown did not land."""
    stamp = read_stamp(db)
    now = int(time.time() // 60)
    age = "no stamp" if stamp is None else f"a stamp {now - stamp} minutes old"
    paths.notes.append(f"the replica has {age}")
    known = last_stamp(paths.data)
    if known is None:
        return
    behind = known - (stamp or 0)
    if behind > BEHIND_MINUTES:
        _refuse(
            paths,
            f"the replica at {paths.replica} is behind what was last written:"
            f" {age if stamp is None else f'{behind} minutes'} behind the last"
            " stamp, so replication had stalled and those writes never reached it."
            " Restoring it loses them, and they are gone with the old pod. Find out"
            " why (the"
            " litestream container's log, if it is still there), then set"
            " litestream.init.override to go on from this replica, or restore a backup",
        )
    elif behind > 0:
        paths.notes.append(
            f"WARNING: the replica is {behind} minutes behind the last stamp: writes"
            " since then did not reach it (a node that died, or a last sync at shutdown"
            " that did not land)"
        )


def _restored(paths: Paths, how: str | None) -> str:
    """The replica, restored into a folder beside the database, then moved in. how is
    None when the state file already says how the database first got here: a restore
    brings the same one back, so only replica_restored_at is new."""
    folder = paths.db.with_name(f"{paths.db.name}.restoring")
    folder.mkdir()
    out = folder / "scrap.db"
    restore_replica(paths.replica, out)
    _too_big(paths, out.stat().st_size, f"the replica at {paths.replica}, restored,")
    _check_stamp(paths, out)
    out.replace(paths.db)
    shutil.rmtree(folder)
    _placed(paths, how, replica_restored_at=now_iso())
    return f"restored {paths.db} from the replica at {paths.replica}"


def _copied(paths: Paths, src: Path, part: Path) -> None:
    """src into part with the backup API (src may have a WAL), checked."""
    wal = fingerprint(Path(f"{src}-wal"))
    size = src.stat().st_size + (wal["size"] if wal else 0)
    _too_big(paths, size, str(src))
    _snapshot(src, part)
    check_db(part)


def _has_pages(legacy: Path) -> bool:
    """Whether the old file is a database anyone used. One made and never written to
    (scrap's start, or a stray sqlite3) must not stand in for a lost one."""
    with closing(connect(legacy)) as conn:
        if not conn.execute("PRAGMA user_version").fetchone()[0]:
            return False
        return conn.execute("SELECT 1 FROM page LIMIT 1").fetchone() is not None


def _from_legacy(paths: Paths) -> str:
    legacy = paths.data / LEGACY
    part = Path(f"{paths.db}.init")
    _copied(paths, legacy, part)
    part.replace(paths.db)
    _placed(paths, "legacy")  # after the copy, which may checkpoint the old file
    return f"brought {legacy} across to {paths.db}, and left it there"


def _from_staged(paths: Paths) -> str:
    """A backup someone chose wins over the replica, which is set aside, not deleted."""
    staged_file = paths.data / STAGED
    newest = newest_file(paths.replica)
    if newest is not None and newest > staged_file.stat().st_mtime:
        _refuse(
            paths,
            f"the replica at {paths.replica} has writes newer than the restore staged"
            f" at {staged_file}, so scrap went on running after it was staged. Taking"
            " it up would lose those writes. Delete the staged file to keep them, or"
            f" to restore anyway, with scrap at 0 replicas: touch {staged_file}",
        )
    part = Path(f"{paths.db}.init")
    _copied(paths, staged_file, part)
    retired = None
    if _present(paths.replica):
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        retired = paths.replica.with_name(f"{paths.replica.name}.retired-{stamp}")
        paths.replica.rename(retired)
    part.replace(paths.db)
    _placed(paths, "staged restore", restored_at=now_iso())
    staged_file.unlink()
    aside = f"; the old replica is now {retired}" if retired else ""
    return f"took up the staged restore into {paths.db}{aside}"


def _fresh(paths: Paths) -> str:
    part = Path(f"{paths.db}.init")
    migrate(part)
    Path(f"{part}.lock").unlink()
    part.replace(paths.db)
    _placed(paths, "new")
    return f"made a new database at {paths.db}"


def _last_restore(state: dict) -> str:
    at = state.get("replica_restored_at")
    return f", last restored from its replica on {at}" if at else ""


def _place(paths: Paths) -> str:
    """The rules at the top of this module, when no database is on the emptyDir."""
    paths.db.parent.mkdir(parents=True, exist_ok=True)
    _clear(paths.db)
    if _present(paths.data / STAGED):
        return _from_staged(paths)
    state = read_state(paths.data)
    legacy = fingerprint(paths.data / LEGACY)
    if has_replica(paths.replica):
        _refuse_changed_legacy(paths, state, legacy)
        return _restored(paths, None if state else "replica")
    if state:
        _refuse(
            paths,
            f"{paths.data / STATE} says a database was put in place on"
            f" {state.get('at')} ({state.get('how')}){_last_restore(state)}, but there"
            f" is no replica at"
            f" {paths.replica}: it was lost, or this is not the volume it was on."
            " Restore a backup (docs/how-to/deploy-kubernetes.md), or if the pod died"
            " before Litestream's first write, set litestream.init.override to start"
            " from what is here",
        )
    if legacy and _has_pages(paths.data / LEGACY):
        return _from_legacy(paths)
    history = _history(paths)
    if history:
        _refuse(
            paths,
            f"no database and no replica, but this install has been used: "
            f"{'; '.join(history)}. The volume may be the wrong one, or empty for a bad"
            " reason. Restore a backup (docs/how-to/deploy-kubernetes.md), or set"
            " litestream.init.override to start empty",
        )
    return _fresh(paths)


def put_in_place(paths: Paths) -> str:
    """Put the database in place. What it did, or InitError."""
    if _present(paths.db):
        if _present(paths.data / STAGED):
            raise InitError(
                f"a restore is staged at {paths.data / STAGED}, but this pod still has"
                f" a live database at {paths.db}. Scale scrap to 0, then back to 1"
            )
        if read_state(paths.data) is None:  # the first start died before noting it
            write_state(paths.data, "kept")
        return f"kept the database already at {paths.db}"
    said = _place(paths)
    if paths.overridden:
        paths.notes.append(
            "WARNING: litestream.init.override went past: "
            + "; ".join(paths.overridden)
            + ". gc only counts until a person runs scrap db-hold --clear"
        )
    return "; ".join([said, *paths.notes])


def _refuse_changed_legacy(
    paths: Paths, state: dict | None, legacy: dict[str, int] | None
) -> None:
    """The replica would win, silently undoing whoever just wrote scrap.db there: most
    likely a plain `scrap restore`, from before Litestream's restore steps. But it may
    be the replica that is newer: so say both, and do neither."""
    legacy_file = paths.data / LEGACY
    if legacy and (not state or state.get("legacy") != legacy):
        _refuse(
            paths,
            f"{legacy_file} has changed since the replica at {paths.replica} began, so"
            " one of them would be lost. The replica may well be the newer copy. To"
            f" keep the replica, rename {legacy_file} away. To keep the file, which"
            f" retires the replica and everything newer in it, rename it to {STAGED};"
            " see docs/how-to/deploy-kubernetes.md",
        )


def from_env() -> str:
    """The init container: settings from the environment; a refusal stops the pod."""
    try:
        limit = os.environ.get("SCRAP_DB_SIZE_LIMIT")
        paths = Paths(
            db=Path(os.environ["SCRAP_DB_PATH"]),
            data=Path(os.environ["SCRAP_DATA_DIR"]),
            replica=Path(os.environ["SCRAP_LITESTREAM_REPLICA"]),
            backups=Path(b) if (b := os.environ.get("SCRAP_BACKUPS")) else None,
            override=os.environ.get("SCRAP_DB_INIT_OVERRIDE", "") == "on",
            size_limit=parse_size(limit) if limit else None,
        )
        # A bad schedule stops the rollout here, rather than a job never running.
        load(os.environ.get("SCRAP_SCHEDULE", "[]"), strict=True)
    except KeyError as error:
        raise SystemExit(f"scrap db-init: {error.args[0]} is not set") from None
    except ValueError as error:
        raise SystemExit(f"scrap db-init: {error}") from None
    try:
        return put_in_place(paths)
    except (
        InitError,
        ReplicaError,
        StateError,
        OSError,
        sqlite3.Error,
        RuntimeError,
    ) as error:
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
    folder, its database under the staged name for the next pod start to take up. Beside
    a live database it would be undone, or undo; and with no sign of Litestream nothing
    would ever take it up."""
    live = os.environ.get("SCRAP_DB_PATH")
    if live and _present(Path(live)):
        raise SystemExit(
            f"scrap restore: {live} exists, so scrap is running here. Scale scrap to 0"
            " and use a one-off restore pod (docs/how-to/deploy-kubernetes.md)"
        )
    replica = os.environ.get("SCRAP_LITESTREAM_REPLICA")
    seen = _present(data_dir / STATE) or _present(data_dir / "litestream")
    if not seen and not (replica and _present(Path(replica))):
        raise SystemExit(
            f"scrap restore: --stage is for an install with Litestream, and {data_dir}"
            " shows no sign of one, so nothing would take the restore up. Without"
            " Litestream, or before its first start, use scrap restore without --stage"
        )
    return Store(data_dir, data_dir / STAGED)
