"""Is replication still working? (ADR 46)

Litestream that cannot write to its replica logs an error and stays up, while scrap goes
on accepting writes the next start would silently roll back. scrap schedule stamps the
database every BEAT, so a replica taking writes always has a file newer than STALE; this
looks, each minute. If there is none it logs, pushes to SCRAP_NOTIFY_URL, and removes
the ok file that the jobs container's readiness probe looks for, so the pod leaves its
Service and scrap stops taking writes it cannot protect. It comes back by itself.

Nothing is called stale until STALE after this started: the first stamp needs time.
"""

import logging
import os
import time
from pathlib import Path

from .dbstate import record_stamp
from .notify import notify
from .replica import newest_file

__all__ = ["OK_FILE", "STALE_SECONDS", "Watch", "db_bytes"]

log = logging.getLogger("scrap.schedule")

# A little over the 15 minute stamp, so one late stamp is not an outage.
STALE_SECONDS = 20 * 60
OK_FILE = ".replication-ok"  # beside the database; the chart's probe wants it young


def db_bytes(db: Path) -> int:
    """All that shares the database's emptyDir: it, its WAL and Litestream's own LTX."""
    total = 0
    for folder, _, names in os.walk(db.parent):
        for name in names:
            try:
                total += os.stat(Path(folder) / name).st_size
            except FileNotFoundError:
                pass
    return total


class Watch:
    def __init__(
        self,
        db: Path,
        data: Path,
        replica: Path,
        size_limit: int | None = None,
        started: float | None = None,
    ):
        self.db = db
        self.data = data
        self.replica = replica
        self.size_limit = size_limit
        self.started = time.time() if started is None else started
        self.stalled = False
        self.too_big = False
        self.ok_file = db.with_name(OK_FILE)
        self.ok_file.touch()

    def stamped(self, stamp: int) -> None:
        """Note the stamp where the next start can compare it. If the volume will not
        take it, Litestream's trouble shows in check; so this only logs."""
        try:
            record_stamp(self.data, stamp)
        except OSError as error:
            log.warning("could not note the stamp on the data volume: %s", error)

    def _problem(self, now: float) -> str | None:
        try:
            newest = newest_file(self.replica)
        except OSError as error:
            return f"cannot read the replica at {self.replica}: {error}"
        if now - self.started < STALE_SECONDS:
            return None
        if newest is None:
            return f"no files in the replica at {self.replica}"
        age = now - newest
        if age > STALE_SECONDS:
            return (
                f"nothing has reached the replica at {self.replica} for"
                f" {age / 60:.0f} minutes"
            )
        return None

    def check(self, now: float | None = None) -> None:
        """Each minute: replication, and how full the emptyDir is."""
        now = time.time() if now is None else now
        problem = self._problem(now)
        if problem:
            if not self.stalled:
                self.stalled = True
                log.error(
                    "REPLICATION STALLED: %s. Taking scrap out of its Service. See"
                    " the litestream container's log",
                    problem,
                )
                notify("scrap: replication stalled; scrap stopped taking writes")
            self.ok_file.unlink(missing_ok=True)
            return
        if self.stalled:
            self.stalled = False
            log.warning("replication is working again")
            notify("scrap: replication is working again")
        self.ok_file.touch()
        self._check_size()

    def _check_size(self) -> None:
        if not self.size_limit:
            return
        used = db_bytes(self.db)
        big = used * 2 > self.size_limit
        if big and not self.too_big:
            log.warning(
                "the database's emptyDir holds %d MB, over half of its limit of %d MB:"
                " raise litestream.sizeLimit before the pod is evicted",
                used // 10**6,
                self.size_limit // 10**6,
            )
            notify("scrap: the database is over half of litestream.sizeLimit")
        self.too_big = big
