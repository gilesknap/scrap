"""A file's ingest job (#234): its text, read here with no model call, for search.

A PDF's text layer is read by pypdf in a child process (pdftext.py) with a timeout and
a memory cap; a text file's is decoded in-process. The text goes in derived as kind
ocr (run_id NULL; the existing trigger indexes it), with data {kind: pdf|text, pages,
pages_read, truncated}, and the job is done. A file that cannot be read kills its job
at once (the same file fails the same way again), with the reason in last_error; it
stays stored and attached. No budget, no pause and no model_run: a file's job is not
held by a paused queue (CLAIM), and has no part in a page's first read or write-up.
"""

import json
import logging
import math
import signal
import sqlite3
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

from ..query import CONTROL
from ..store import MAX_PAGE, SURROGATE, Store, now, transaction
from ..store.helpers import file_kind
from . import pdftext
from .jobs import kill, put_derived

MAX_FILE = 30 * 2**20  # bytes: a larger file is stored and attached, not read
MAX_PAGES = 200  # a PDF's first pages read
MAX_CHARS = 500_000  # characters of text kept (and indexed)
TIMEOUT = 60.0  # seconds the PDF reader may take
MEMORY = 512 * 2**20  # bytes of address space the PDF reader may have
# The child: the module's file run as a script (-I: no user site, nor scrap's package
# imports), not -m scrap.ingest.pdftext, which would import the service first
COMMAND = [sys.executable, "-I", pdftext.__file__]
ENV = {"LC_ALL": "C.UTF-8"}  # all the child gets: none of the service's secrets

log = logging.getLogger(__name__)


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
    cpu = math.ceil(TIMEOUT) + 5  # the child's own backstop
    args = [str(path), str(MAX_PAGES), str(MAX_CHARS), str(MEMORY), str(cpu)]
    slow = FileError("timeout", f"reading the PDF took over {TIMEOUT:g} s")
    try:  # stdout only: it is at most MAX_CHARS of text; stderr could be anything
        done = subprocess.run(
            [*COMMAND, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=ENV,
            timeout=TIMEOUT,
            check=False,
        )  # killed on the timeout
    except subprocess.TimeoutExpired:
        raise slow from None
    if done.returncode == pdftext.OUT_OF_MEMORY:
        raise FileError("memory", f"reading the PDF needed over {_mb(MEMORY)}")
    if done.returncode == -signal.SIGXCPU:
        raise slow
    if done.returncode == pdftext.ENCRYPTED:
        raise FileError("content", "the PDF could not be read (it needs a password)")
    if done.returncode != 0:
        raise FileError("content", "the PDF could not be read")
    try:
        out = json.loads(done.stdout)
        text, cut = _clean(out["text"])
        return {"pages": int(out["pages"]), "pages_read": int(out["pages_read"]),
                "text": text, "truncated": bool(out["truncated"]) or cut}  # fmt: skip
    except (ValueError, KeyError, TypeError):
        raise FileError("content", "the PDF could not be read") from None


def read(path: Path, kind: str) -> tuple[dict[str, Any], str]:
    """A file's text and data, and the producer to record; FileError if unreadable."""
    size = path.stat().st_size
    if size > MAX_FILE:
        raise FileError("too large", f"{_mb(size)}, over the {_mb(MAX_FILE)} limit")
    if kind == "pdf":
        return read_pdf(path), f"pypdf {version('pypdf')}"
    return read_text(path), "scrap"


def process(store: Store, job: sqlite3.Row, mime: str) -> None:
    """Run a file's job: its text in derived and the job done, or the job dead (any
    failure: trying again would fail the same way, so none is charged and retried)."""
    try:
        _process(store, job, mime)
    except Exception as error:  # noqa: BLE001  a missing file, the child not starting
        if not isinstance(error, FileError):
            log.exception("file job %s", job["id"])
            error = FileError("internal", type(error).__name__)
        with store.connect() as conn, transaction(conn):
            kill(conn, job["id"], now(), str(error))


def _process(store: Store, job: sqlite3.Row, mime: str) -> None:
    jid, cid, sha = job["id"], job["capture_id"], job["source_sha256"]
    kind = file_kind(mime) or "text"
    path, _ = store.blob(sha)
    got, producer = read(path, kind)
    stamp = now()
    with store.connect() as conn, transaction(conn):
        state = conn.execute("SELECT state FROM job WHERE id = ?", (jid,)).fetchone()
        if state is None or state[0] != "running":
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
