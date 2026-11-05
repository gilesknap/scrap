"""What stops scrap gc deleting on a Litestream install (ADR 46).

gc deletes the files nothing refers to, so a database that came back older than the
files makes the newest files look unused. That is the one loss a restore cannot undo, so
here gc only counts when:

- a person used litestream.init.override, until they clear it (scrap db-hold --clear); -
a restore was taken up in the last RESTORE_HOLD_DAYS: files added since that backup are
unused now, and someone may want to go through them; - the database has no captures but
files/ has content; - the files to delete are more than MAX_UNUSED_SHARE of them, and at
least MIN_UNUSED. A healthy night deletes few. --allow-large goes ahead, after a person
has looked.

Without Litestream (the database in the data folder) gc is as it always was.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .dbstate import StateError, read_state
from .gc import Report, collect
from .store import Store

__all__ = ["Hold", "MAX_UNUSED_SHARE", "MIN_UNUSED", "RESTORE_HOLD_DAYS", "guarded"]

# Low on purpose: a false alarm costs one flag on one night; a miss deletes originals.
MAX_UNUSED_SHARE = 0.10
MIN_UNUSED = 5
RESTORE_HOLD_DAYS = 14


@dataclass
class Hold:
    why: str
    fails: bool = True  # the run fails, so it is noticed; else it is only logged


def _from_state(store: Store) -> Hold | None:
    try:
        state = read_state(store.dir)
    except StateError as error:
        return Hold(f"{error}: counting only")
    if not state:
        return None
    if state.get("override_at"):
        return Hold(
            f"litestream.init.override was used at {state['override_at']}"
            f" ({state.get('override_why', 'reason not recorded')}): counting only"
            " until a person has looked and run scrap db-hold --clear"
        )
    if at := state.get("restored_at"):
        until = datetime.fromisoformat(at) + timedelta(days=RESTORE_HOLD_DAYS)
        if datetime.now(UTC) < until:
            return Hold(
                f"a restore was taken up at {at}: files added since that backup look"
                f" unused, so counting only until {until.date()}"
                " (scrap db-hold --clear to end this sooner)",
                fails=False,
            )
    return None


def _total_files(store: Store) -> int:
    total = 0
    for _, _, names in os.walk(store.files):
        total += sum(1 for name in names if not name.startswith("."))
    return total


def _from_content(store: Store, report: Report) -> Hold | None:
    total = _total_files(store)
    if not total:
        return None
    with store.connect() as conn:
        captures = conn.execute("SELECT count(*) FROM capture").fetchone()[0]
    if not captures:
        return Hold(
            f"the database has no captures but files/ holds {total} files: it may have"
            " come back empty. Counting only; --allow-large deletes after a person has"
            " looked"
        )
    if report.unused >= MIN_UNUSED and report.unused / total > MAX_UNUSED_SHARE:
        return Hold(
            f"{report.unused} of {total} files would go, over the limit of"
            f" {MAX_UNUSED_SHARE:.0%}: the database may have come back older than the"
            " files. Counting only; --allow-large deletes after a person has looked"
        )
    return None


def guarded(
    store: Store,
    delete: bool,
    allow_large: bool,
    grace_hours: float,
    run_days: float,
    **kw: Any,
) -> tuple[Report, Hold | None]:
    """gc.collect, with the holds above if this is a Litestream install."""
    if not delete or store.db == store.dir / "scrap.db":
        return collect(store, delete, grace_hours, run_days, **kw), None
    hold = _from_state(store)
    if hold:
        return collect(store, False, grace_hours, run_days, **kw), hold
    if not allow_large:
        report = collect(store, False, grace_hours, run_days, **kw)
        hold = _from_content(store, report)
        if hold:
            return report, hold
    return collect(store, True, grace_hours, run_days, **kw), None
