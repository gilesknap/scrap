"""The notes a Litestream install keeps on its data volume (ADR 46): plain files, so a
pod, a one-off restore pod and gc can all read them, and nothing depends on the
database.

- The state file says a database was put in place here, so a lost replica is noticed. It
also holds what stops gc deleting for now: an override used, or a restore taken up. -
The health file holds the last stamp written to the live database, so the next start can
tell how far behind the replica it restores is.

With neither file (every install without Litestream) nothing here does anything.
"""

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "HEALTH",
    "LEGACY",
    "STAGED",
    "STATE",
    "StateError",
    "clear_hold",
    "forget",
    "forget_if_here",
    "fingerprint",
    "last_stamp",
    "parse_size",
    "read_state",
    "record_stamp",
    "refuse_old_database",
    "write_state",
]

STATE = ".scrap-db-state.json"
HEALTH = ".scrap-replica-health.json"
STAGED = "scrap.db.restored"  # from scrap restore --stage
LEGACY = "scrap.db"  # where the database lived before
SIZE = re.compile(r"([0-9]+)(Ki|Mi|Gi|Ti|K|M|G|T)?")
UNITS = {
    None: 1,
    "K": 10**3,
    "M": 10**6,
    "G": 10**9,
    "T": 10**12,
    "Ki": 2**10,
    "Mi": 2**20,
    "Gi": 2**30,
    "Ti": 2**40,
}


class StateError(RuntimeError):
    """The notes say this cannot go ahead, or cannot be read."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_size(text: str) -> int:
    """A Kubernetes quantity such as 2Gi, in bytes. ValueError if it is not one."""
    found = SIZE.fullmatch(text.strip())
    if not found:
        raise ValueError(f"not a size: {text!r}")
    return int(found[1]) * UNITS[found[2]]


def fingerprint(path: Path) -> dict[str, int] | None:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def read_state(data: Path) -> dict[str, Any] | None:
    """The state file, None if there is none. One that is not ours says nothing safe, so
    it is an error, not "no state"."""
    path = data / STATE
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except ValueError as error:
        raise StateError(f"{path} is not readable: {error}") from None
    if not isinstance(state, dict) or "how" not in state:
        raise StateError(f"{path} is not readable: no 'how' in it")
    return state


def _write_json(path: Path, value: dict[str, Any]) -> None:
    part = path.with_name(f"{path.name}.part")
    with open(part, "w") as out:
        json.dump(value, out)
        out.flush()
        os.fsync(out.fileno())
    part.replace(path)


def write_state(data: Path, how: str | None = None, **fields: Any) -> None:
    """Update the state file, keeping what it holds: how the database got here, when,
    and the old file's fingerprint as it is now."""
    state = read_state(data) or {}
    state.update(fields)
    state["how"] = how or state.get("how", "unknown")
    state["at"] = now_iso()
    state["legacy"] = fingerprint(data / LEGACY)
    _write_json(data / STATE, state)


def clear_hold(data: Path) -> str:
    """A person has looked: gc may delete again. What was cleared."""
    state = read_state(data)
    if not state or not ({"override_at", "restored_at"} & state.keys()):
        return "nothing is holding gc back"
    held = [f"{k} {state.pop(k)}" for k in ("override_at", "restored_at") if k in state]
    state.pop("override_why", None)
    _write_json(data / STATE, state)
    return f"cleared {', '.join(held)}: gc may delete again"


def forget(data: Path) -> None:
    """The database is back in the data folder: the way off Litestream."""
    (data / STATE).unlink(missing_ok=True)
    (data / HEALTH).unlink(missing_ok=True)


def forget_if_here(db: Path, data: Path) -> None:
    """After a plain restore into the data folder."""
    if db == data / LEGACY:
        forget(data)


def record_stamp(data: Path, stamp: int) -> None:
    _write_json(data / HEALTH, {"last_stamp": stamp})


def last_stamp(data: Path) -> int | None:
    """The stamp last written to the live database, as recorded; None if unknown. A
    damaged note is only unknown: this file is a check, not the data."""
    try:
        stamp = json.loads((data / HEALTH).read_text()).get("last_stamp")
    except (FileNotFoundError, ValueError, AttributeError):
        return None
    return stamp if isinstance(stamp, int) else None


def refuse_old_database(db: Path, data: Path) -> None:
    """Without Litestream, on a data folder that had it (the setting turned off, or a
    rollback): /data/scrap.db is the copy from before. Serving it would lose everything
    since, and gc would then delete the files only the newer database uses."""
    if db != data / LEGACY:
        return
    try:
        os.stat(data / STATE)
    except (FileNotFoundError, NotADirectoryError):
        return
    raise StateError(
        f"{data / STATE} says this install's database is replicated by Litestream, but"
        f" scrap was started on {db}, the old copy from before that. Nothing was"
        " changed. Turn litestream.enabled back on, or leave it as"
        " docs/how-to/deploy-kubernetes.md describes: restoring a backup with"
        " scrap restore --force clears this"
    )
