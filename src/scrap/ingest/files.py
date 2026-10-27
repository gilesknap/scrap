"""A file's ingest job (#234): its text, read here with no model call, for search.

A PDF's text layer is read by pypdf in a child process (pdftext.py) with a timeout and
a memory cap; a text file's is decoded in-process. The text goes in derived as kind
ocr (run_id NULL; the existing trigger indexes it), with data {kind: pdf|text, pages,
pages_read, truncated}, and the job is done. A file whose content cannot be read (not a
PDF, corrupt, encrypted, too large, over the memory cap) kills its job at once (the
same file fails the same way again), with the reason in last_error; it stays stored and
attached. A transient failure (the child not starting, a timeout under load) is charged
and retried, three times at most (jobs.charge). A file already read (same hash, same
reader) is not parsed again: its text is copied. No budget, no pause and no model_run:
a file's job is not held by a paused queue (CLAIM), and has no part in a page's first
read or write-up.
"""

import json
import logging
import math
import signal
import sqlite3
import subprocess
import sys
import threading
from importlib.metadata import version
from pathlib import Path
from typing import Any

from ..query import CONTROL
from ..store import MAX_PAGE, SURROGATE, Store, now, transaction
from ..store.helpers import file_kind
from . import pdftext
from .jobs import charge, kill, put_derived

MAX_FILE = 30 * 2**20  # bytes: a larger file is stored and attached, not read
MAX_PAGES = 200  # a PDF's first pages read
MAX_CHARS = 500_000  # characters of text kept (and indexed)
TIMEOUT = 60.0  # seconds the PDF reader may take
MEMORY = 512 * 2**20  # bytes of address space the PDF reader may have
# The child: the module's file run as a script (-I: no user site, nor scrap's package
# imports), not -m scrap.ingest.pdftext, which would import the service first
COMMAND = [sys.executable, "-I", pdftext.__file__]
ENV = {"LC_ALL": "C.UTF-8"}  # all the child gets: none of the service's secrets

MAGIC = b"%PDF-"  # a PDF has it within its first KiB (readers allow junk before)
HEAD = 1024

log = logging.getLogger(__name__)
_children: set[subprocess.Popen[bytes]] = set()  # PDF readers running now
_lock = threading.Lock()


def stop_children() -> None:
    """Kill the PDF readers running (at shutdown: the service goes, they would not)."""
    with _lock:
        running = list(_children)
    for child in running:
        child.kill()


class FileError(Exception):
    """A file that cannot be read: its class (content, too large, timeout, memory)
    and what to say."""

    def __init__(self, cls: str, message: str):
        super().__init__(f"{cls}: {message}")


def _mb(size: int) -> str:
    return f"{size / 2**20:.0f} MB"


def _clean(text: str) -> tuple[str, bool]:
    """Text within MAX_CHARS, then made safe to index (no control characters: snippets
    mark hits with them; no lone surrogates) and within the most a derived text holds
    (MAX_PAGE bytes); whether either cut it."""
    cut = len(text) > MAX_CHARS
    text = SURROGATE.sub("", CONTROL.sub(" ", text[:MAX_CHARS]))
    data = text.encode()
    if len(data) > MAX_PAGE:
        text, cut = data[:MAX_PAGE].decode(errors="ignore"), True
    return text, cut


def read_text(path: Path) -> dict[str, Any]:
    """A text file's text: UTF-8 (a byte that is not becomes U+FFFD), BOM dropped. Only
    as many bytes as MAX_CHARS characters can take are read (4 a character, and the
    BOM)."""
    room = 4 * MAX_CHARS + 3
    with path.open("rb") as file:
        data = file.read(room + 1)
    text = data[:room].decode("utf-8-sig", errors="replace")
    text, cut = _clean(text)
    cut = cut or len(data) > room
    return {"pages": None, "pages_read": None, "text": text, "truncated": cut}


def read_pdf(path: Path) -> dict[str, Any]:
    """A PDF's text layer (pdftext.py, in a child process); FileError if unreadable."""
    with path.open("rb") as file:
        if MAGIC not in file.read(HEAD):  # no child for what is plainly not a PDF
            raise FileError("content", "the PDF could not be read (it is not a PDF)")
    cpu = math.ceil(TIMEOUT) + 5  # the child's own backstop
    args = [str(path), str(MAX_PAGES), str(MAX_CHARS), str(MEMORY), str(cpu)]
    slow = FileError("timeout", f"reading the PDF took over {TIMEOUT:g} s")
    # stdout only: it is at most MAX_CHARS of text; stderr could be anything
    with subprocess.Popen(
        [*COMMAND, *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=ENV,
    ) as child:
        with _lock:
            _children.add(child)
        try:
            stdout, _ = child.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            child.kill()  # Popen's exit waits for it
            raise slow from None
        finally:
            with _lock:
                _children.discard(child)
    code = child.returncode
    if code == pdftext.OUT_OF_MEMORY:
        raise FileError("memory", f"reading the PDF needed over {_mb(MEMORY)}")
    if code == -signal.SIGXCPU:
        raise slow
    if code == pdftext.ENCRYPTED:
        raise FileError("content", "the PDF could not be read (it needs a password)")
    if code != 0:
        raise FileError("content", "the PDF could not be read")
    try:
        out = json.loads(stdout)
        text, cut = _clean(out["text"])
        return {"pages": int(out["pages"]), "pages_read": int(out["pages_read"]),
                "text": text, "truncated": bool(out["truncated"]) or cut}  # fmt: skip
    except (ValueError, KeyError, TypeError):
        raise FileError("content", "the PDF could not be read") from None


def producer_of(kind: str) -> str:
    return f"pypdf {version('pypdf')}" if kind == "pdf" else "scrap"


def read(path: Path, kind: str) -> tuple[dict[str, Any], str]:
    """A file's text and data, and the producer to record; FileError if unreadable."""
    size = path.stat().st_size
    if size > MAX_FILE:
        raise FileError("too large", f"{_mb(size)}, over the {_mb(MAX_FILE)} limit")
    if kind == "pdf":
        return read_pdf(path), producer_of(kind)
    return read_text(path), producer_of(kind)


def process(store: Store, job: sqlite3.Row, mime: str) -> None:
    """Run a file's job: its text in derived and the job done. A file that cannot be
    read is dead at once (trying again would fail the same way); a transient failure
    (an OSError, as the reader not starting, or a timeout under load) is charged and
    retried later, the third killing the job."""
    try:
        _process(store, job, mime)
    except Exception as error:  # noqa: BLE001  a missing file, the child not starting
        if not isinstance(error, FileError):
            log.exception("file job %s", job["id"])
            retry = isinstance(error, OSError)  # the reader did not start, disk full
            error = FileError("internal", type(error).__name__)
        else:
            retry = str(error).startswith("timeout:")
        cls, _, message = str(error).partition(": ")
        with store.connect() as conn, transaction(conn):
            if not retry:
                kill(conn, job["id"], now(), str(error))
            elif _running(conn, job["id"]):
                charge(conn, job["id"], cls, now(), message)


def _running(conn: sqlite3.Connection, job_id: int) -> bool:
    row = conn.execute("SELECT state FROM job WHERE id = ?", (job_id,)).fetchone()
    return row is not None and row[0] == "running"


def _known(conn: sqlite3.Connection, sha: str, kind: str) -> sqlite3.Row | None:
    """The current reading of this file by this reader, from any capture of it."""
    return conn.execute(
        "SELECT text, data FROM derived WHERE source_sha256 = ? AND kind = 'ocr'"
        " AND producer = ? AND superseded_at IS NULL AND json_valid(data)"
        " AND json_extract(data, '$.kind') = ? ORDER BY id DESC LIMIT 1",
        (sha, producer_of(kind), kind),
    ).fetchone()


def _process(store: Store, job: sqlite3.Row, mime: str) -> None:
    jid, cid, sha = job["id"], job["capture_id"], job["source_sha256"]
    kind = file_kind(mime) or "text"
    with store.connect() as conn:
        known = _known(conn, sha, kind)
    if known is not None:  # read before (another capture, Reprocess): not parsed again
        got = {**json.loads(known["data"]), "text": known["text"]}
        got.pop("kind", None)
        producer = producer_of(kind)
    else:
        path, _ = store.blob(sha)
        got, producer = read(path, kind)
    stamp = now()
    with store.connect() as conn, transaction(conn):
        if not _running(conn, jid):
            return  # purged, or given back at shutdown: it runs again
        text = got.pop("text")
        put_derived(
            conn, cid, sha, "ocr", producer, stamp, text=text,
            data={"kind": kind, **got},
        )  # fmt: skip
        conn.execute(
            "UPDATE job SET state = 'done', last_error = NULL, updated_at = ?"
            " WHERE id = ?",
            (stamp, jid),
        )
