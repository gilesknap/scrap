"""``scrap shrink``: make the photos already stored smaller, as the PWA now does
before it queues one (#89): at most ``MAX_EDGE`` px on the long edge, JPEG at
quality 85.

The phone does this in the browser (``web/src/downscale.ts``), so there is no Python
helper to share. This module uses the decoder ``scrap.preview`` already has (upright
by EXIF orientation, flattened to RGB or L, colour profile kept where it still
applies, one decode at a time) and the same numbers; ``MAX_EDGE``, ``QUALITY`` and
``TYPES`` mirror the constants in downscale.ts.

A stored file is addressed by its SHA-256, so a smaller photo is a new file. For each
one that shrinks, in one write transaction (the kind a capture or edit takes, so it
is safe while scrap serves), every reference moves to the new file:

- the ``capture_blob`` rows (a ``.heic`` name becomes ``.jpg``), the ``derived``
  rows (Claude's readings and drawings: their immutability trigger is lifted for the
  update and put back, inside the transaction), and the ``job`` and ``model_run``
  rows;
- the address ``/api/blobs/<sha>`` in the text of every page that has it, trash
  included, as a text revision by ``AUTHOR`` and a new search chunk. ``updated_at``
  is left alone: nothing the reader sees changed;
- then the old file, if nothing else refers to it (``scrap.gc.in_use``, so a model
  run's sent JPEG counts), is removed with its previews, as ``scrap gc`` removes one.

A photo is left as it is when it is not a JPEG, HEIC, HEIF or WebP, is at or under
the limit, would not get smaller, cannot be read, or cannot be repointed (a conflict
rolls its transaction back). Each photo has its own transaction, so a run stopped
halfway keeps what it did, and running again does the rest; a second run finds
nothing to do. Revisions of a page's text from before keep the old address: a revert
to one shows a missing image, so take a backup first (``scrap backup``).
"""

import fcntl
import io
import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import gc, preview
from .store import InvalidError, Store, now, transaction
from .store.constants import REV_INSERT
from .store.indexing import index_page

__all__ = ["AUTHOR", "MAX_EDGE", "QUALITY", "ShrinkError", "Report", "run"]

log = logging.getLogger(__name__)

MAX_EDGE = 2560  # web/src/downscale.ts MAX_EDGE
QUALITY = 85  # downscale.ts QUALITY (0.85)
TYPES = ("image/jpeg", "image/heic", "image/heif", "image/webp")  # downscale.ts SHRUNK
AUTHOR = "scrap shrink"  # the revisions' author
LOCK = gc.LOCK  # the lock a deleting scrap gc holds: one maintenance run at a time


class ShrinkError(Exception):
    """The run could not start or go on; nothing further was changed."""


@dataclass
class Item:
    sha: str
    size: int  # before
    new_size: int  # after
    width: int
    height: int
    pages: int  # pages whose text has its address (trash too)
    captures: int  # capture_blob rows


@dataclass
class Report:
    """What a run found (and did): counts and sizes only, never any page text."""

    items: list[Item] = field(default_factory=list)  # shrunk, or to shrink
    small: int = 0  # at or under the limit
    bigger: int = 0  # would not get smaller
    unreadable: int = 0  # missing, not an image, too large to decode
    failed: int = 0  # could not be repointed: left as it was
    other_types: int = 0  # PNG, GIF and the rest
    removed: int = 0  # old files removed (apply)
    kept: int = 0  # old files kept: still in use, or touched meanwhile
    applied: bool = False

    @property
    def saved(self) -> int:
        return sum(i.size - i.new_size for i in self.items)

    def text(self) -> str:
        mb = lambda n: f"{n / 2**20:.1f} MB"  # noqa: E731
        lines = [
            f"  {i.sha[:12]}  {i.width}x{i.height}  {mb(i.size)} -> {mb(i.new_size)}"
            f"  ({i.pages} pages, {i.captures} captures)"
            for i in self.items
        ]
        before = sum(i.size for i in self.items)
        verb = "shrank" if self.applied else "would shrink"
        lines.append(
            f"scrap shrink: {verb} {len(self.items)} photos over {MAX_EDGE} px,"
            f" {mb(before)} -> {mb(before - self.saved)}, saving {mb(self.saved)}"
            + (
                f"; removed {self.removed} old files, kept {self.kept}"
                if self.applied
                else " (dry run: --apply shrinks them; back up first)"
            )
        )
        lines.append(
            f"left alone: {self.small} within {MAX_EDGE} px, {self.bigger} that"
            f" would not get smaller, {self.other_types} not JPEG, HEIC or WebP,"
            f" {self.unreadable} unreadable"
            + (f", {self.failed} that could not be repointed" if self.failed else "")
        )
        return "\n".join(lines)


def _size(path: Path) -> tuple[int, int] | None:
    """A file's pixel size from its header, None if it is not an image."""
    try:
        with Image.open(path) as im:
            return im.size
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def smaller(path: Path) -> tuple[bytes, tuple[int, int]] | None:
    """The photo as an upright JPEG of at most MAX_EDGE px, and its size; None if it is
    too large to decode or not an image."""
    try:
        with preview.decoder:
            im, extra = preview.decode(path, MAX_EDGE)
            out = io.BytesIO()
            im.save(out, "JPEG", quality=QUALITY, **extra)
    except (InvalidError, OSError, ValueError):
        return None
    return out.getvalue(), im.size


def _jpeg_name(name: str | None) -> str | None:
    """The name with a .jpg ending (.jpeg kept), as downscale.ts jpegName."""
    if name is None or name.lower().endswith((".jpg", ".jpeg")):
        return name
    stem, dot, ext = name.rpartition(".")
    return (stem if dot and 1 <= len(ext) <= 5 and ext.isalnum() else name) + ".jpg"


def _repoint(
    conn: sqlite3.Connection, old: str, new: str, size: int, stamp: str
) -> None:
    """Move every reference from old to new; the caller's transaction is open."""
    conn.execute(
        "INSERT INTO blob VALUES (?, 'image/jpeg', ?, ?) ON CONFLICT DO NOTHING",
        (new, size, stamp),
    )
    for cid, ordinal, name in conn.execute(
        "SELECT capture_id, ord, filename FROM capture_blob WHERE sha256 = ?", (old,)
    ).fetchall():
        conn.execute(
            "UPDATE capture_blob SET sha256 = ?, filename = ?"
            " WHERE capture_id = ? AND ord = ?",
            (new, _jpeg_name(name), cid, ordinal),
        )
    conn.execute("UPDATE job SET source_sha256 = ? WHERE source_sha256 = ?", (new, old))
    conn.execute(
        "UPDATE model_run SET source_sha256 = ? WHERE source_sha256 = ?", (new, old)
    )
    if conn.execute("SELECT 1 FROM derived WHERE source_sha256 = ?", (old,)).fetchone():
        trigger = "derived_immutable"  # a version never changes, but where it points
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            (trigger,),
        ).fetchone()
        if sql is None:
            raise sqlite3.DatabaseError(f"no trigger {trigger}")
        conn.execute(f"DROP TRIGGER {trigger}")
        conn.execute(
            "UPDATE derived SET source_sha256 = ? WHERE source_sha256 = ?", (new, old)
        )
        conn.execute(sql[0])
    for page_id, title, body in conn.execute(
        "SELECT id, title, body FROM page WHERE instr(body, ?)", (old,)
    ).fetchall():
        rev = conn.execute(
            "SELECT max(rev) FROM page_rev WHERE page_id = ?", (page_id,)
        ).fetchone()[0]
        body = body.replace(old, new)
        conn.execute("UPDATE page SET body = ? WHERE id = ?", (body, page_id))
        conn.execute(REV_INSERT, (page_id, rev + 1, title, body, AUTHOR, "web", stamp))
        index_page(conn, page_id)


def _uses(conn: sqlite3.Connection, sha: str) -> tuple[int, int]:
    pages = conn.execute(
        "SELECT count(*) FROM page WHERE instr(body, ?)", (sha,)
    ).fetchone()[0]
    caps = conn.execute(
        "SELECT count(*) FROM capture_blob WHERE sha256 = ?", (sha,)
    ).fetchone()[0]
    return pages, caps


def _one(
    store: Store,
    report: Report,
    sha: str,
    mime: str,
    size: int,
    apply: bool,
    grace: float,
) -> None:
    path = store.blob_path(sha)
    if mime not in TYPES:
        report.other_types += 1
        return
    dims = _size(path) if path.is_file() else None
    if dims is None:
        report.unreadable += 1
        return
    if max(dims) <= MAX_EDGE:
        report.small += 1
        return
    made = smaller(path)
    if made is None:
        report.unreadable += 1
        return
    data, (width, height) = made
    if len(data) >= size:
        report.bigger += 1
        return
    with store.connect() as conn:
        pages, caps = _uses(conn, sha)
    item = Item(sha, size, len(data), width, height, pages, caps)
    if not apply:
        report.items.append(item)
        return
    new, _ = store.put_blob(io.BytesIO(data))  # young: gc spares it until recorded
    if new == sha:
        report.bigger += 1
        return
    cutoff = time.time() - grace * 3600
    stamp = now()
    with store.connect() as conn:
        try:
            with transaction(conn):
                if (
                    conn.execute(
                        "SELECT 1 FROM blob WHERE sha256 = ?", (sha,)
                    ).fetchone()
                    is None
                ):
                    report.unreadable += 1  # gone since it was listed
                    return
                _repoint(conn, sha, new, len(data), stamp)
                gone = sha not in gc.in_use(conn) and gc.delete_file(
                    store, sha, path, cutoff
                )
                if gone:
                    conn.execute("DELETE FROM blob WHERE sha256 = ?", (sha,))
        except sqlite3.Error as error:  # rolled back: left as it was
            log.warning("scrap shrink: %s left as it was: %s", sha, error)
            report.failed += 1
            return
    report.items.append(item)
    report.removed += gone
    report.kept += not gone


def run(
    store: Store,
    apply: bool = False,
    grace_hours: float = gc.GRACE_HOURS,
    progress: Callable[[str], None] | None = None,
) -> Report:
    """Find (and with apply, shrink) the stored photos over MAX_EDGE px; see the module.

    grace_hours: an old file touched more recently than this (an upload of the same
    bytes) is kept, as scrap gc keeps it."""
    if grace_hours < 0:
        raise ShrinkError("the grace period must not be negative")
    if not store.db.is_file():
        raise ShrinkError(f"no database at {store.db}")
    report = Report(applied=apply)
    try:
        gc.schema_version(store.db)  # refuses a database newer than this scrap
        with store.connect() as conn:
            rows = conn.execute(
                "SELECT sha256, mime, size FROM blob WHERE mime LIKE 'image/%'"
                " ORDER BY size DESC"
            ).fetchall()
    except sqlite3.Error as error:
        raise ShrinkError(f"cannot read the database: {error}") from None
    if not apply:
        for sha, mime, size in rows:
            _one(store, report, sha, mime, size, False, grace_hours)
        return report
    try:
        lock = open(store.dir / LOCK, "w")  # noqa: SIM115 (closed when the run ends)
    except OSError as error:
        raise ShrinkError(f"cannot take the lock {store.dir / LOCK}: {error}") from None
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ShrinkError(
                f"scrap gc or another scrap shrink is running (it holds"
                f" {store.dir / LOCK}); try again when it has finished"
            ) from None
        gc.restore_aside(store)  # a file an earlier gc left aside
        for sha, mime, size in rows:
            _one(store, report, sha, mime, size, True, grace_hours)
            if progress:
                progress(sha)
    return report
