"""The ingest queue and its worker: each photo goes to Claude once, in the background.

One daemon thread in the service claims one job at a time, calls Claude holding no lock,
then records the run and its results in one transaction. Outages and spending problems
pause the whole queue and refund the claim; every other failure is charged to the job,
and its third kills it. See docs/explanations/ingest.md.
"""

from ..store import now
from .constants import (
    CLAIM,
    FAR,
    INSERT_DERIVED,
    MAX_FAILURES,
    PAUSES,
    POLL,
    RETRY,
    REV,
    TITLE_CAS,
)
from .jobs import (
    charge,
    claim,
    enabled,
    later,
    midnight_after,
    notify,
    pause,
    put_derived,
    recover,
    resume,
    spent_today,
)
from .ops import reprocess, resume_queue, status
from .worker import Call, Worker

__all__ = [
    "CLAIM",
    "FAR",
    "INSERT_DERIVED",
    "MAX_FAILURES",
    "PAUSES",
    "POLL",
    "RETRY",
    "REV",
    "TITLE_CAS",
    "Call",
    "Worker",
    "charge",
    "claim",
    "enabled",
    "later",
    "midnight_after",
    "notify",
    "now",
    "pause",
    "put_derived",
    "recover",
    "reprocess",
    "resume",
    "resume_queue",
    "spent_today",
    "status",
]
