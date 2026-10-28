"""Enrich: a file page's own reading, unasked (ADR 38). With SCRAP_FILE_ENRICH auto,
file ingest queues a page made from files an enrich job of reason capture once its
first capture's files are read (store.queue_after_file); no other capture job reaches
such a page (roles.NOT_BY_INGEST). That job is sent the start of the files' text, less
than Ask is, under #378's rules (quoted, no list of actions applied)."""

import sqlite3
from typing import NamedTuple

from ..store import file_enrich, roles
from .constants import (
    AUTO_FILES,
    AUTO_RELATED_FILES,
    MAX_FILES,
    RELATED_FILES,
    SHORT,
    UNTITLED_FILE,
)
from .prompts import File, file_text, page_files

# The page has an enrichment that another job made (an Ask, say, meanwhile): this one
# is not sent again. Its own (an earlier try of it, whose related call failed) is not.
OTHERS = """
SELECT 1 FROM enrichment e LEFT JOIN enrich_run r ON r.id = e.run_id
WHERE e.page_id = :page AND r.job_id IS NOT :job
"""


def unasked(conn: sqlite3.Connection, reason: str, page_id: str) -> bool:
    """Whether a job of this reason is a file page's own reading (reason capture on a
    page whose first capture is a file capture)."""
    return reason == "capture" and roles.file_first(conn, page_id)


def skipped(
    conn: sqlite3.Connection, page_id: str, job_id: int, files: list[File]
) -> bool:
    """Whether a file page's own reading makes no call: SCRAP_FILE_ENRICH set to ask
    since it was queued, too little read (under SHORT characters), or the page
    enriched by another job meanwhile."""
    return (
        file_enrich() != "auto"
        or len(file_text(files)) < SHORT
        or conn.execute(OTHERS, {"page": page_id, "job": job_id}).fetchone() is not None
    )


def limits(asked: bool) -> tuple[int, int]:
    """The characters of the files' text sent to enrich and to related: Ask's, or
    less on a file page's own reading."""
    return (MAX_FILES, RELATED_FILES) if asked else (AUTO_FILES, AUTO_RELATED_FILES)


class Sent(NamedTuple):
    """What an enrich job sends of a page's files: whether it sends their text (sent),
    the files (none if not), whether a summary an Ask made is kept (keep: text was read
    from them but is not sent, #378), whether a title is asked for (untitled: a page
    made from a file, FILE_UNTITLED), and the characters of their text sent to enrich
    and related (most, related_most)."""

    sent: bool
    files: list[File]
    keep: bool
    untitled: bool
    most: int
    related_most: int


def files_sent(conn: sqlite3.Connection, job: sqlite3.Row, page_id: str) -> Sent | None:
    """What a job sends of a page's files: on Ask (ADR 35, #378), and on a file page's
    own reading, less (ADR 38); nothing for any other job. None: a file page's own
    reading that makes no call (skipped)."""
    asked = job["reason"] == "ask"
    auto = unasked(conn, job["reason"], page_id)
    sent, files = asked or auto, page_files(conn, page_id)
    keep = not sent and bool(file_text(files))
    files = files if sent else []
    if auto and skipped(conn, page_id, job["id"], files):
        return None
    untitled = sent and bool(conn.execute(UNTITLED_FILE, {"page": page_id}).fetchone())
    return Sent(sent, files, keep, untitled, *limits(asked))
