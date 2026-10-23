"""Storage: one SQLite database and a folder of content-addressed files."""

import fcntl
import hashlib
import html
import json
import math
import os
import re
import secrets
import sqlite3
import tempfile
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, date, datetime
from importlib.resources import files as package_files
from pathlib import Path
from typing import IO, Any, NamedTuple

from .markdown import plain, tasks
from .query import CONTROL, PRIORITIES, Query, bound, day, due, parse

__all__ = [
    "Store", "NotFoundError", "NoSuchPage", "NoSuchRevision", "ConflictError",
    "TooLargeError", "InvalidError",
    "clean_tags",
]  # fmt: skip

BlobRef = tuple[str, str, int, str | None]  # sha256, mime, size, filename
ULID = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")
SHA256 = re.compile(r"[0-9a-f]{64}")
BARE_URL = re.compile(r"https?://\S+")
# Ranking: bm25 weights of a page's title, tags, summary and text (chunk_fts's columns)
WEIGHTS = "10.0, 5.0, 3.0, 1.0"
# Each part stops at the next bracket, so no line takes more than linear time
MD_LINK = re.compile(
    r"!?\[([^\[\]\n]*)\]\((?:<[^<>\n]*>|[^()\s]*)(?:\s+\"[^\"\n]*\")?\)"
)
WIKI_LINK = re.compile(r"\[\[([^\[\]|\n]+)(?:\|([^\[\]\n]+))?\]\]")
# A file's address in a page's text (see body_refs). Linear: no backtracking.
BLOB_ADDRESS = re.compile(r"/api/blobs/([0-9a-f]{64})")
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
# The kinds a user can choose (memory and reference are in the schema, not offered yet),
# and the fields a page gets when it becomes that kind
KINDS = ("note", "todo", "consume", "whiteboard", "document")
DEFAULT_FIELDS = {
    "todo": {"status": "open"},
    "consume": {"subtype": "read", "status": "open"},
}
HINTS = ("todo", "consume")  # the older capture field, still accepted
ALL_KINDS = (*KINDS, "memory", "reference")  # in the schema, so a filter may ask
# kind: in a search also takes the PWA's names for kinds
# A page p's thumbnail: the SHA-256 of its first image, if any (SQL, for a column)
THUMB = (
    "(SELECT b.sha256 FROM capture c JOIN capture_blob cb"
    " ON cb.capture_id = c.id JOIN blob b USING (sha256)"
    " WHERE c.page_id = p.id AND b.mime LIKE 'image/%'"
    # not one whose embed was deleted from the text (see Store.removed)
    " AND (instr(p.body, '/api/blobs/' || b.sha256) OR NOT EXISTS (SELECT 1"
    " FROM page_rev r WHERE r.page_id = p.id"
    " AND instr(r.body, '/api/blobs/' || b.sha256)))"
    " ORDER BY c.received_at, cb.ord LIMIT 1)"
)
# Search filters on a page p's images (SQL): has:image, has:drawing, and image:K (the
# kind Claude gave a photo: photo, whiteboard, screenshot...)
HAS = {
    "image": "EXISTS (SELECT 1 FROM capture c JOIN capture_blob cb"
    " ON cb.capture_id = c.id JOIN blob b USING (sha256)"
    " WHERE c.page_id = p.id AND b.mime LIKE 'image/%')",
    "drawing": "EXISTS (SELECT 1 FROM capture c JOIN derived d ON d.capture_id = c.id"
    " WHERE c.page_id = p.id AND d.kind = 'excalidraw' AND d.superseded_at IS NULL)",
}
IMAGE_KIND = (
    "EXISTS (SELECT 1 FROM capture c JOIN derived d ON d.capture_id = c.id"
    " WHERE c.page_id = p.id AND d.kind = 'description' AND d.superseded_at IS NULL"
    " AND json_extract(d.data, '$.kind') = ?)"
)
KIND_NAMES = {
    "later": "consume",
    "read": "consume",
    "board": "whiteboard",
    "doc": "document",
}
# What each sort: orders a page p by (query.SORTS has its default direction)
SORT_SQL = {
    "updated": "p.updated_at",
    "created": "p.created_at",
    "title": "p.title COLLATE NOCASE",  # ASCII letters only: SQLite has no ICU here
    # A todo's: other kinds keep theirs (see the migration) but have none here
    "due": "CASE WHEN p.kind = 'todo' THEN p.due END",
    "priority": "CASE WHEN p.kind = 'todo' THEN CASE p.priority"
    " WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 END END",
}
TODO = ("due", "priority", "snoozed_until")  # a todo's own columns
TODO_SQL = "p.kind = 'todo' AND "  # a filter on them: only a todo's count
RANK = "coalesce(p.priority, 'none')"  # priority:none finds a todo with none
# Priorities as an imported todo may have them (Thoth's Urgent: the highest there is)
PRIORITY_NAMES = {"urgent": "high"}
SOURCES = ("pwa", "share")  # a capture's, from a client; "mcp" only from scrap.mcp
MCP = "mcp"  # the source of a page Claude wrote, over MCP
# The author of what Claude writes over MCP: of its captures, and of its text revisions
# (page_rev). Only MCP writes as it: the PWA's author is a Tailscale login (an address,
# with an @) or "tagged", so a text revision by CLAUDE is one made over MCP.
CLAUDE = "claude"
MAX_FIELDS = 32  # a page's fields are listed with every page: keep them small
MAX_TAGS = 64  # a page's, as the PWA sets them (MCP's write takes fewer)
MAX_TAG = 64  # characters, as the tag table's CHECK has it
MAX_PAGE = 1_000_000  # bytes of UTF-8: a page's text, however it is written (#62)
KINDS_SHOWN = ("ocr", "description", "excalidraw")
META_SOURCES = ("web", "mcp")  # who changed a page's kind or tags: the PWA, or Claude
# Every change to a page's kind and tags, newest first (see page_meta_rev)
META_REV = (
    "SELECT id, page_id, author, source, kind_before, kind_after, fixed_before,"
    " fixed_after, tags_before, tags_after, fields_added, reverts, batch_id,"
    " created_at, updated_at FROM page_meta_rev"
)
# One ingest job per distinct image of a photo capture (or the one photo asked for);
# job_one_active makes a repeat add nothing.
ENQUEUE = """
INSERT INTO job (kind, capture_id, source_sha256, options, run_after, created_at,
                 updated_at)
SELECT DISTINCT 'ingest', cb.capture_id, cb.sha256, :options, :now, :now, :now
FROM capture_blob cb
JOIN capture c ON c.id = cb.capture_id AND (c.kind = 'photo' OR :photo IS NOT NULL)
JOIN blob b ON b.sha256 = cb.sha256 AND b.mime LIKE 'image/%'
WHERE cb.capture_id = :capture AND coalesce(:photo, cb.sha256) = cb.sha256
ON CONFLICT DO NOTHING
"""


class NotFoundError(Exception):
    """No such page or blob (or it is in the trash)."""


class NoSuchPage(NotFoundError):  # noqa: N818
    """No such page (or it is in the trash); the message is the key given."""


class NoSuchRevision(NotFoundError):  # noqa: N818
    """No such revision or batch; the message names it ("revision 9")."""


class ConflictError(Exception):
    """A page edit was based on an older revision."""


class TooLargeError(Exception):
    """An upload is over the size limit."""


class InvalidError(Exception):
    """A request is malformed."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_ulid() -> str:
    n = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    return "".join(CROCKFORD[(n >> shift) & 31] for shift in range(125, -1, -5))


def upload_limit() -> int:
    """The largest upload (and imported file), from SCRAP_MAX_UPLOAD_MB."""
    value = os.environ.get("SCRAP_MAX_UPLOAD_MB", "50")
    try:
        return int(float(value) * 2**20)
    except ValueError:
        raise SystemExit(
            f"SCRAP_MAX_UPLOAD_MB must be a number, not {value!r}"
        ) from None


def revision_window() -> float:
    """Seconds within which one author's changes to a page's kind and tags fold into
    one revision, from SCRAP_REVISION_WINDOW (default 300; 0: every change is one)."""
    value = os.environ.get("SCRAP_REVISION_WINDOW", "300")
    try:
        window = float(value)
    except ValueError:
        window = -1.0
    if not window >= 0:  # also NaN
        raise SystemExit(
            f"SCRAP_REVISION_WINDOW must be a number of seconds, not {value!r}"
        )
    return window


def seconds_between(earlier: str, later: str) -> float:
    """The seconds from one of now()'s timestamps to another."""
    start, end = datetime.fromisoformat(earlier), datetime.fromisoformat(later)
    return (end - start).total_seconds()


def too_big(size: int, most: int = MAX_PAGE) -> str:
    """Why a page of size bytes is refused: in bytes, so the boundary is clear."""
    mb = " (1 MB)" if most == MAX_PAGE else ""
    return f"the page text is {size:,} bytes, and a page holds at most {most:,}{mb}"


def check_page(body: str, was: str | None = None) -> str:
    """body, if it is within MAX_PAGE bytes of UTF-8 or is unchanged from was (a page
    imported over the limit can still be retitled); else InvalidError, saying so."""
    size = len(body.encode())
    if size > MAX_PAGE and body != was:
        raise InvalidError(too_big(size))
    return body


def unlink(text: str) -> str:
    """Markdown text with each link or image reduced to its label, and a page link to
    its label (else slug): addresses are not words to search for. Not handled:
    reference definitions ([r]: url), link text holding brackets, a URL with
    parentheses (leaves a ")"), and code (unlinked too)."""
    text = WIKI_LINK.sub(lambda m: m[2] or m[1], text)
    return MD_LINK.sub(r"\1", text)


def body_refs(text: str) -> set[str]:
    """The stored files a page's text refers to, by SHA-256: any mention of a file's
    address counts (an image, a link, even in code), so a page never loses a file it
    shows. The one place page text is read for references (scrap gc, the save warning's
    counts). Deliberately not the Markdown parser (markdown.py): gc deletes what this
    misses, so it errs on keeping a file (in code, an absolute URL, broken Markdown)."""
    return set(BLOB_ADDRESS.findall(text))


def embeds(blobs: list[tuple[str, str, int, str | None]], text: str) -> list[str]:
    """Markdown that shows each image of a capture in its page's text, in order (once
    each, none the text shows already): a page's photos are shown there, the text the
    user then owns."""
    images = dict.fromkeys(sha for sha, mime, *_ in blobs if mime.startswith("image/"))
    return [
        f"![](/api/blobs/{sha}/preview?size=2048)"
        for sha in images
        if f"](/api/blobs/{sha}" not in text
    ]


def clean_tags(tags: list[str], most: int = MAX_TAGS) -> list[str]:
    """Tags as imported ones are: one space between words, no leading #, lower case;
    each 1 to 64 characters, at most most of them, each once, in order."""
    if len(tags) > most:
        raise InvalidError(f"at most {most} tags")
    out: list[str] = []
    for tag in tags:
        try:
            tag.encode()
        except UnicodeEncodeError:
            raise InvalidError("a tag must be valid Unicode") from None
        new = " ".join(CONTROL.sub(" ", tag).split()).lstrip("#").lower().strip()
        new = unicodedata.normalize("NFC", new)
        if not new or len(new) > MAX_TAG:
            raise InvalidError(f"a tag must be 1 to {MAX_TAG} characters: {tag[:80]!r}")
        if new not in out:
            out.append(new)
    return out


def check_todo(name: str, value: Any) -> str | None:
    """A due date or a day snoozed until (YYYY-MM-DD) or a priority (high, medium,
    low) as given, checked; None clears it."""
    if value is None:
        return None
    if name in ("due", "snoozed_until"):
        if not isinstance(value, str) or day(value) is None:
            raise InvalidError(f"{name} must be a date, YYYY-MM-DD")
        return value
    if value not in PRIORITIES:
        raise InvalidError(f"priority must be one of {PRIORITIES}")
    return value


def todo_columns(
    kind: str, fields: dict[str, Any]
) -> tuple[dict[str, str | None], dict[str, Any]]:
    """A todo's due and priority, out of fields it was imported with (Thoth's due_date
    and priority: kept in fields if not a date or a priority), and the other fields."""
    out: dict[str, str | None] = dict.fromkeys(TODO)
    if kind != "todo":
        return out, fields
    rest = dict(fields)
    for name in ("due", "snoozed_until"):  # an export's front matter has them too
        if isinstance(when := rest.get(name), str) and day(when):
            out[name] = rest.pop(name)
    rank = rest.get("priority")
    rank = PRIORITY_NAMES.get(rank, rank) if isinstance(rank, str) else None
    if rank in PRIORITIES:
        out["priority"] = rank
        rest.pop("priority")
    return out, rest


def todo_only(page: dict[str, Any]) -> dict[str, Any]:
    """A page (or a list's row) with its due and priority if it is a todo, else None;
    and its task boxes as tasks: {done, total} (any kind's)."""
    if page.get("kind") != "todo":
        page.update(dict.fromkeys(TODO))
    if "task_total" in page:
        page["tasks"] = {"done": page.pop("task_done"), "total": page.pop("task_total")}
    return page


HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)")  # an ATX heading's marker


def slug_base(title: str) -> str:
    """A slug made from a title, before any suffix that makes it unique."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore")
    base = re.sub(r"[^a-z0-9]+", "-", ascii_title.decode().lower())[:60].strip("-")
    return base or "page"


def migrations() -> list[str]:
    """The numbered migration scripts, in order: script N sets user_version N."""
    folder = package_files("scrap") / "migrations"
    scripts = sorted((p for p in folder.iterdir() if p.name.endswith(".sql")), key=str)
    return [p.read_text() for p in scripts]


def connect(db: Path | str) -> sqlite3.Connection:
    """Open the database in autocommit mode with the per-connection pragmas."""
    conn = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise InvalidError(f"{key} must be a string")
    return lines(value).strip() or None if value else None


def lines(text: str) -> str:
    """Unix line ends: multipart form fields arrive with CRLF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


Value = str | int | float | bool  # a field's value: flat, no nulls
MAX_INT = 2**53  # the most a browser holds exactly: a field's number is within +-this


def check_value(name: str, value: Any) -> None:
    """Refuse a field value the PWA could not show as stored: a float that is not
    finite (NaN, Infinity, or 1e400, which parses to it) or an int past +-2**53."""
    if isinstance(value, bool):
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidError(f"field {name}: a number must be finite")
    if isinstance(value, int) and abs(value) > MAX_INT:
        raise InvalidError(f"field {name}: a whole number is at most +-2**53")


def fields_for(kind: str | None, url: str | None) -> dict[str, Value]:
    """A kind's default fields; consume also links its source, if it has one."""
    fields: dict[str, Value] = dict(DEFAULT_FIELDS.get(kind or "", {}))
    if kind == "consume" and url:
        fields["source"] = url
    return fields


def _rows(conn: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, args)]


def schema_version(db: Path) -> int:
    """A database's schema version, refusing one newer than this code knows."""
    conn = connect(db)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    if version > len(migrations()):
        raise RuntimeError(
            f"{db} has schema {version}; this scrap knows {len(migrations())}"
        )
    return version


def migrate(db: Path) -> None:
    """Apply the missing migrations, one process at a time (flock on db.lock). A
    migration's Python step (AFTER) runs in its transaction, after its script."""
    with open(f"{db}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        version = schema_version(db)
        with closing(connect(db)) as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            for n, sql in enumerate(migrations()[version:], start=version + 1):
                try:
                    conn.executescript(f"BEGIN IMMEDIATE;\n{sql}")
                    if n in AFTER:
                        AFTER[n](conn)
                    conn.execute(f"PRAGMA user_version = {n}")
                    conn.execute("COMMIT")
                except BaseException:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise


def index_page(conn: sqlite3.Connection, page_id: str) -> None:
    """(Re)make a page's own search chunk from its title, tags, summary and body (its
    derived text has chunks of its own). No control characters: snippets mark hits
    with \x02 and \x03. Each becomes a space, so a lone \r or \v still separates two
    words."""
    title, body, fields = conn.execute(
        "SELECT title, body, fields FROM page WHERE id = ?", (page_id,)
    ).fetchone()
    tags = " ".join(
        r[0] for r in conn.execute("SELECT tag FROM tag WHERE page_id = ?", (page_id,))
    )
    summary = json.loads(fields).get("summary")
    summary = summary if isinstance(summary, str) else model_summary(conn, page_id)
    # The text as words (markdown.py); the others are short, and not Markdown
    parts = (unlink(title), tags, unlink(summary), plain(body))
    clean = [CONTROL.sub(" ", x) for x in parts]
    conn.execute(
        "DELETE FROM chunk WHERE page_id = ? AND derived_id IS NULL", (page_id,)
    )
    conn.execute(
        "INSERT INTO chunk (page_id, ord, title, tags, summary, text)"
        " VALUES (?, 0, ?, ?, ?, ?)",
        (page_id, *clean),
    )


def model_summary(conn: sqlite3.Connection, page_id: str) -> str:
    """The summary Claude wrote for a page (enrich), else ''. Before migration 9 there
    is no enrichment table: ''."""
    try:
        row = conn.execute(
            "SELECT summary FROM enrichment WHERE page_id = ?", (page_id,)
        ).fetchone()
    except sqlite3.OperationalError:
        return ""
    return row[0] if row else ""


def enrich_on() -> bool:
    """Whether Claude enriches text pages: with ingest on (SCRAP_INGEST), unless
    SCRAP_ENRICH is off."""
    on = ("on", "1", "true", "yes")
    ingest = os.environ.get("SCRAP_INGEST", "off").lower() in on
    return ingest and os.environ.get("SCRAP_ENRICH", "on").lower() in on


# The page kinds Claude reads for tags and a summary: notes (a saved link is one), todos
# and reads (consume). A photo, whiteboard or document page is not read as text (#155).
# Ask Claude is an explicit act and still works on any page.
ENRICH_KINDS = ("note", "todo", "consume")


# A page with a photo or file capture is read by ingest, not enrich, whatever its kind
# (a photo page is stored as a note until ingest reclassifies it).
NOT_BY_INGEST = (
    "NOT EXISTS (SELECT 1 FROM capture c WHERE c.page_id = {p}.id"
    " AND c.kind IN ('photo', 'file'))"
)


def should_enrich(conn: sqlite3.Connection, page_id: str) -> bool:
    """Whether enrich reads this page on a capture, save or backfill: its kind is in
    ENRICH_KINDS and it has no photo or file capture."""
    row = conn.execute(
        "SELECT p.kind FROM page p WHERE p.id = ? AND " + NOT_BY_INGEST.format(p="p"),
        (page_id,),
    ).fetchone()
    return row is not None and row[0] in ENRICH_KINDS


def debounce() -> float:
    """Seconds an enrich job waits after a save, so a burst of edits makes one call."""
    try:
        return max(0.0, float(os.environ.get("SCRAP_ENRICH_DEBOUNCE", "60")))
    except ValueError:
        return 60.0


def stamp_after(seconds: float) -> str:
    t = datetime.now(UTC).timestamp() + seconds
    return (
        datetime.fromtimestamp(t, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


# One queued enrich job per page: a later trigger moves it (a save later, Ask now), and
# Ask is remembered (it may add tags to a page Claude has read before)
ENRICH_ENQUEUE = """
INSERT INTO enrich_job (page_id, reason, run_after, created_at, updated_at)
VALUES (:page, :reason, :run_after, :now, :now)
ON CONFLICT (page_id) WHERE state = 'queued' DO UPDATE SET
    run_after = excluded.run_after,
    reason = CASE WHEN reason = 'ask' THEN reason ELSE excluded.reason END,
    updated_at = excluded.updated_at
"""


def queue_enrich(
    conn: sqlite3.Connection, page_id: str, reason: str, delay: float = 0.0
) -> None:
    """Queue (or move) a page's enrich job, to run in delay seconds."""
    conn.execute(
        ENRICH_ENQUEUE,
        {"page": page_id, "reason": reason, "run_after": stamp_after(delay),
         "now": now()},
    )  # fmt: skip


def index_all(conn: sqlite3.Connection) -> None:
    """Every page's own chunk again (the trash's too: undo brings a page back)."""
    for (page_id,) in conn.execute("SELECT id FROM page").fetchall():
        index_page(conn, page_id)


def move_todo_fields(conn: sqlite3.Connection) -> None:
    """Each todo's due and priority fields (as imported from Thoth) into its columns."""
    for page_id, fields in conn.execute(
        "SELECT id, fields FROM page WHERE kind = 'todo'"
    ).fetchall():
        todo, rest = todo_columns("todo", json.loads(fields))
        if any(todo.values()):
            conn.execute(
                "UPDATE page SET due = ?, priority = ?, fields = ? WHERE id = ?",
                (todo["due"], todo["priority"], json.dumps(rest), page_id),
            )


def add_snooze(conn: sqlite3.Connection) -> None:
    """A todo's snoozed_until (migration 6), unless an earlier run added it."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(page)")}
    if "snoozed_until" not in columns:
        conn.execute(
            "ALTER TABLE page ADD COLUMN snoozed_until TEXT CHECK (snoozed_until"
            " IS NULL OR (length(snoozed_until) = 10"
            " AND date(snoozed_until) = snoozed_until))"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS page_by_snooze ON page(snoozed_until)"
        " WHERE snoozed_until IS NOT NULL"
    )


def add_tasks(conn: sqlite3.Connection) -> None:
    """Each page's task box counts (migration 7): the columns if missing, counted."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(page)")}
    for name in ("task_done", "task_total"):
        if name not in columns:
            conn.execute(
                f"ALTER TABLE page ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0"
            )
    for page_id, body in conn.execute("SELECT id, body FROM page").fetchall():
        conn.execute(
            "UPDATE page SET task_done = ?, task_total = ? WHERE id = ?",
            (*tasks(body), page_id),
        )


def add_meta_revs(conn: sqlite3.Connection) -> None:
    """The revisions of pages' kinds and tags (migration 8), unless an earlier run made
    them. tags_* are JSON arrays, sorted; fixed_* the page's kind_fixed; fields_added
    the default fields a new kind added (a revert takes them off); reverts the
    revision a revert undid; batch_id shared by one bulk change's revisions."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS page_meta_rev ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"  # an id is never used again
        " page_id TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,"
        " author TEXT NOT NULL,"
        " source TEXT NOT NULL CHECK (source IN ('web', 'mcp')),"
        " kind_before TEXT NOT NULL,"
        " kind_after TEXT NOT NULL,"
        " fixed_before INTEGER NOT NULL CHECK (fixed_before IN (0, 1)),"
        " fixed_after INTEGER NOT NULL CHECK (fixed_after IN (0, 1)),"
        " tags_before TEXT NOT NULL CHECK (json_type(tags_before) = 'array'),"
        " tags_after TEXT NOT NULL CHECK (json_type(tags_after) = 'array'),"
        " fields_added TEXT NOT NULL DEFAULT '{}'"
        "  CHECK (json_type(fields_added) = 'object'),"
        " reverts INTEGER REFERENCES page_meta_rev(id),"
        " batch_id TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL)"
    )
    for name, columns in (
        ("by_page", "page_id, id"), ("by_reverts", "reverts"), ("by_batch", "batch_id"),
    ):  # fmt: skip
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS page_meta_rev_{name}"
            f" ON page_meta_rev({columns})"
        )


ENRICH_TABLES = """
CREATE TABLE IF NOT EXISTS enrich_job (
    id          INTEGER PRIMARY KEY,
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    reason      TEXT NOT NULL CHECK (reason IN ('capture', 'save', 'ask', 'backfill')),
    state       TEXT NOT NULL DEFAULT 'queued'
                  CHECK (state IN ('queued', 'running', 'done', 'dead')),
    failures    INTEGER NOT NULL DEFAULT 0,
    run_after   TEXT NOT NULL,
    last_error  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS enrich_job_one_queued ON enrich_job(page_id)
    WHERE state = 'queued';
CREATE INDEX IF NOT EXISTS enrich_job_ready ON enrich_job(state, run_after);
CREATE TABLE IF NOT EXISTS enrich_run (
    id             INTEGER PRIMARY KEY,
    page_id        TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    job_id         INTEGER REFERENCES enrich_job(id) ON DELETE SET NULL,
    model          TEXT NOT NULL,
    served_model   TEXT,
    prompt_version TEXT NOT NULL,
    request        TEXT NOT NULL CHECK (json_valid(request)),
    response       TEXT CHECK (json_valid(response)),
    output         TEXT CHECK (json_valid(output)),
    usage          TEXT CHECK (json_valid(usage)),
    cost_microusd  INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'ok', 'invalid', 'refused', 'error')),
    error_class    TEXT,
    error          TEXT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT
);
CREATE INDEX IF NOT EXISTS enrich_run_by_started ON enrich_run(started_at);
CREATE INDEX IF NOT EXISTS enrich_run_by_page ON enrich_run(page_id);
CREATE TABLE IF NOT EXISTS enrichment (
    page_id     TEXT PRIMARY KEY REFERENCES page(id) ON DELETE CASCADE,
    run_id      INTEGER REFERENCES enrich_run(id),
    producer    TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    source      TEXT,
    source_title TEXT,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_tag (
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    state       TEXT NOT NULL CHECK (state IN ('on', 'off')),
    producer    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (page_id, tag)
);
CREATE TABLE IF NOT EXISTS related (
    page_id     TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    other_id    TEXT NOT NULL REFERENCES page(id) ON DELETE CASCADE,
    rank        INTEGER NOT NULL,
    PRIMARY KEY (page_id, other_id)
);
CREATE INDEX IF NOT EXISTS related_by_other ON related(other_id);
"""


def add_enrich(conn: sqlite3.Connection) -> None:
    """Enrich's tables (migration 9), unless an earlier run made them."""
    for statement in ENRICH_TABLES.split(";"):
        if statement.strip():
            conn.execute(statement)


AFTER = {
    3: index_all, 4: index_all, 5: move_todo_fields, 6: add_snooze, 7: add_tasks,
    8: add_meta_revs,
    9: add_enrich,
}  # fmt: skip


class Meta(NamedTuple):
    """A page's kind, whether it is fixed (kind_fixed), and tags (sorted): what
    page_meta_rev keeps of it, before and after a change."""

    kind: str
    fixed: int
    tags: list[str]


def meta_of(row: sqlite3.Row, when: str) -> Meta:
    """A page_meta_rev row's state before or after (when) its change."""
    return Meta(
        row[f"kind_{when}"], row[f"fixed_{when}"], json.loads(row[f"tags_{when}"])
    )


def meta_row(row: sqlite3.Row) -> dict[str, Any]:
    """A page_meta_rev row as data: its tags as lists, and those added and removed."""
    before, after = json.loads(row["tags_before"]), json.loads(row["tags_after"])
    return {
        **dict(row), "tags_before": before, "tags_after": after,
        "fixed_before": bool(row["fixed_before"]),
        "fixed_after": bool(row["fixed_after"]),
        "fields_added": json.loads(row["fields_added"]),
        "tags_added": [t for t in after if t not in before],
        "tags_removed": [t for t in before if t not in after],
    }  # fmt: skip


def boxes_before(page: sqlite3.Row) -> tuple[int, int]:
    """A page's task boxes (ticked, all) before an edit, as its status follows them: a
    todo's counts; none for a page that was not a todo, so one filed as a todo by this
    edit (by its boxes, or by hand) is filed as a new capture of its text would be: done
    if every box is ticked."""
    return (page["task_done"], page["task_total"]) if page["kind"] == "todo" else (0, 0)


def tag_counts(rows: list[Any]) -> dict[str, int]:
    """How many pages have each tag, from (page id, tag) rows: a/b counts for a too."""
    pages: dict[str, set[str]] = {}
    for page_id, tag in rows:
        parts = tag.split("/")
        for n in range(1, len(parts) + 1):
            pages.setdefault("/".join(parts[:n]), set()).add(page_id)
    return {tag: len(ps) for tag, ps in pages.items()}


class Store:
    def __init__(self, data_dir: Path | str):
        self.dir = Path(data_dir)
        self.db = self.dir / "scrap.db"
        self.files = self.dir / "files"
        self.window = revision_window()  # seconds: see _record_meta

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self.db)
        try:
            yield conn
        finally:
            conn.close()

    def migrate(self) -> None:
        """Create the data folder and bring the schema up to date."""
        self.files.mkdir(parents=True, exist_ok=True)
        migrate(self.db)

    def blob_path(self, sha: str) -> Path:
        return self.files / sha[:2] / sha

    def put_blob(self, src: IO[bytes]) -> tuple[str, int]:
        """Copy an upload into files/ under its SHA-256."""
        digest, size = hashlib.sha256(), 0
        with tempfile.NamedTemporaryFile(dir=self.files, prefix=".up-") as tmp:
            while chunk := src.read(1 << 20):
                size += len(chunk)
                digest.update(chunk)
                tmp.write(chunk)
            tmp.flush()
            os.fsync(tmp.fileno())
            sha = digest.hexdigest()
            dest = self.blob_path(sha)
            dest.parent.mkdir(exist_ok=True)
            while True:
                try:
                    os.link(tmp.name, dest)
                    break
                except FileExistsError:  # the same bytes, saved before
                    try:  # young again: scrap gc spares it until this is recorded
                        os.utime(dest)
                        break
                    except FileNotFoundError:  # scrap gc deleted it just now
                        continue
        return sha, size

    def prepare(self, data: dict[str, Any], mimes: list[str]) -> dict[str, Any]:
        """Check a capture request (before any file is written) and derive its page.

        mimes are the types of its files, if any.
        """
        cid = (_text(data, "id") or "").upper()
        if not ULID.fullmatch(cid):
            raise InvalidError("id must be a ULID")
        text, url, hint = _text(data, "text"), _text(data, "url"), _text(data, "hint")
        kind = _text(data, "kind")
        source = _text(data, "source") or "pwa"
        created = _text(data, "created_at") or now()
        try:
            when = datetime.fromisoformat(created)
        except ValueError:
            raise InvalidError("created_at must be ISO 8601") from None
        if source not in SOURCES:
            raise InvalidError(f"source must be one of {SOURCES}")
        if hint not in (None, *HINTS):
            raise InvalidError(f"hint must be one of {HINTS}")
        if kind not in (None, *KINDS):
            raise InvalidError(f"kind must be one of {KINDS}")
        kind = kind or hint
        todo = {k: check_todo(k, _text(data, k)) for k in TODO}
        if kind != "todo" and any(todo.values()):
            raise InvalidError("due and priority are for todos")
        if not url and text and BARE_URL.fullmatch(text):
            url, text = text, None  # a link shared as text
        if mimes:
            images = all(mime.startswith("image/") for mime in mimes)
            what = "photo" if images else "file"
        else:
            what = "url" if url else "note"
        if what == "note" and not text:
            raise InvalidError("empty capture")
        tags = data.get("tags")
        if tags is None:  # only missing or null means none: "" or {} is refused below
            tags = []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise InvalidError("tags must be a list of strings")
        tags = clean_tags(tags)  # as an edit's
        # Its first line without a heading's #s ("# Trip notes" is titled Trip notes)
        first = text.splitlines()[0] if text else ""
        title = (HEADING.sub("", first).strip() or first)[:200] if text else url
        return {
            "id": cid, "kind": what, "text": text, "url": url, "source": source,
            "created_at": created, "page_kind": kind, "fields": fields_for(kind, url),
            **todo,
            "title": title or when.strftime("%Y-%m-%d %H:%M"),
            "body": check_page("\n\n".join(x for x in (url, text) if x)),
            "tags": tags,
        }  # fmt: skip

    def capture(
        self,
        c: dict[str, Any],
        blobs: list[tuple[str, str, int, str | None]],
        author: str,
        tags: list[str] | None = None,
    ) -> tuple[dict[str, str], bool]:
        """Save a prepared capture as a new page, with these tags (else the
        capture's own, if any). Returns its reference and whether it is new. blobs
        are (sha256, mime, size, filename), already in files/.
        """
        cid, title, body, kind = c["id"], c["title"], c["body"], c["page_kind"]
        tags = c.get("tags") if tags is None else tags
        body = check_page("\n\n".join(x for x in (body, *embeds(blobs, body)) if x))
        stamp = now()
        with self.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT page_id FROM capture WHERE id = ?", (cid,)
            ).fetchone()
            if row:
                return self._ref(conn, cid, row[0]), False
            conn.executemany(
                "INSERT INTO blob VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                [(sha, mime, size, stamp) for sha, mime, size, _ in blobs],
            )
            page_id = new_ulid()
            conn.execute(
                "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
                " created_at, updated_at, due, priority, snoozed_until)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (page_id, self._slug(conn, title), title, body, kind or "note",
                 int(bool(kind)), json.dumps(c["fields"]), stamp, stamp,
                 c.get("due"), c.get("priority"), c.get("snoozed_until")),
            )  # fmt: skip
            conn.execute(
                "INSERT INTO page_rev VALUES (?, 1, ?, ?, ?, ?)",
                (page_id, title, body, author, stamp),
            )
            conn.execute(
                "INSERT INTO capture VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, c["kind"], c["text"], c["url"], c["source"], author,
                 c["created_at"], stamp, page_id),
            )  # fmt: skip
            conn.executemany(
                "INSERT INTO capture_blob VALUES (?, ?, ?, ?)",
                [(cid, i, sha, name) for i, (sha, _, _, name) in enumerate(blobs)],
            )
            conn.executemany(
                "INSERT INTO tag VALUES (?, ?)", [(page_id, t) for t in tags or []]
            )
            self._body(conn, page_id)
            self.reindex(conn, page_id)
            conn.execute(ENQUEUE, {"capture": cid, "photo": None, "options": "{}",
                                   "now": stamp})  # fmt: skip
            if (
                enrich_on()
                and c["kind"] in ("note", "url")  # a photo has ingest
                and should_enrich(conn, page_id)
            ):
                # A link is fetched at once; a note waits, in case it is edited now
                wait = 0.0 if c["kind"] == "url" else debounce()
                queue_enrich(conn, page_id, "capture", wait)
            return self._ref(conn, cid, page_id), True

    def import_page(
        self,
        p: dict[str, Any],
        captures: list[tuple[str, str, str | None, list[BlobRef]]],
        author: str,
        enqueue: bool = False,
    ) -> tuple[str, bool]:
        """Save a page made elsewhere (scrap import) with its own slug, kind, fields,
        tags and dates. captures are (id, kind, text, blobs), blobs already in files/;
        the first id is the retry key, as for a capture. Its text, the original, also
        keeps ingest from retitling the page. Returns the slug and whether it is new.
        enqueue: send its photos to Claude, as a capture would.
        """
        for name, value in p["fields"].items():
            check_value(name, value)
        stamp = now()
        with self.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT p.slug FROM capture c JOIN page p ON p.id = c.page_id"
                " WHERE c.id = ?",
                (captures[0][0],),
            ).fetchone()
            if row:
                return row[0], False
            blobs = [b for *_, bs in captures for b in bs]
            conn.executemany(
                "INSERT INTO blob VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                [(sha, mime, size, stamp) for sha, mime, size, _ in blobs],
            )
            page_id = new_ulid()
            todo, fields = todo_columns(p["kind"], p["fields"])
            conn.execute(
                "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
                " created_at, updated_at, due, priority, snoozed_until)"
                " VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
                (page_id, p["slug"], p["title"], p["body"], p["kind"],
                 json.dumps(fields), p["created_at"], p["updated_at"], todo["due"],
                 todo["priority"], todo["snoozed_until"]),
            )  # fmt: skip
            conn.execute(
                "INSERT INTO page_rev VALUES (?, 1, ?, ?, ?, ?)",
                (page_id, p["title"], p["body"], author, p["updated_at"]),
            )
            for cid, kind, text, bs in captures:
                conn.execute(
                    "INSERT INTO capture VALUES (?, ?, ?, NULL, 'import', ?, ?, ?, ?)",
                    (cid, kind, text, author, p["created_at"], stamp, page_id),
                )
                conn.executemany(
                    "INSERT INTO capture_blob VALUES (?, ?, ?, ?)",
                    [(cid, i, sha, name) for i, (sha, _, _, name) in enumerate(bs)],
                )
                if enqueue:
                    conn.execute(ENQUEUE, {"capture": cid, "photo": None,
                                           "options": "{}", "now": stamp})  # fmt: skip
            conn.executemany(
                "INSERT INTO tag VALUES (?, ?)", [(page_id, t) for t in p["tags"]]
            )
            self._body(
                conn, page_id, follow=False
            )  # counted; its kind and status as it was
            self.reindex(conn, page_id)
            return p["slug"], True

    def slugs(self) -> set[str]:
        """Every slug in use, the trash's too (a trashed page keeps its slug)."""
        if not self.db.is_file():
            return set()
        with self.connect() as conn:
            return {row[0] for row in conn.execute("SELECT slug FROM page")}

    def imported(self, ids: list[str]) -> dict[str, str]:
        """The slug of the page each of these capture ids made, for those that exist."""
        if not self.db.is_file():
            return {}
        with self.connect() as conn:
            return {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT c.id, p.slug FROM capture c JOIN page p ON p.id = c.page_id"
                    " WHERE c.id IN (SELECT value FROM json_each(?))",
                    (json.dumps(ids),),
                )
            }

    def _ref(self, conn: sqlite3.Connection, cid: str, page_id: str) -> dict[str, str]:
        slug = conn.execute("SELECT slug FROM page WHERE id = ?", (page_id,)).fetchone()
        return {"capture_id": cid, "page_id": page_id, "slug": slug[0]}

    def _slug(self, conn: sqlite3.Connection, title: str) -> str:
        base = slug_base(title)
        taken = {
            row[0]
            for row in conn.execute(
                "SELECT slug FROM page WHERE slug = ? OR slug GLOB ? || '-[0-9]*'",
                (base, base),
            )
        }
        slug, n = base, 1
        while slug in taken:
            n += 1
            slug = f"{base}-{n}"
        return slug

    def reindex(self, conn: sqlite3.Connection, page_id: str) -> None:
        """Index a page's current title, tags, summary and body again."""
        index_page(conn, page_id)

    def _page_row(self, conn: sqlite3.Connection, key: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT *, (SELECT max(rev) FROM page_rev WHERE page_id = page.id) AS rev"
            " FROM page WHERE (id = ? OR slug = ?) AND deleted_at IS NULL",
            (key, key),
        ).fetchone()
        if row is None:
            raise NoSuchPage(key)
        return row

    def recent(self, limit: int, kind: str | None = None) -> list[dict[str, Any]]:
        """Pages, newest change first; only those of one kind, if given."""
        if kind not in (None, *ALL_KINDS):
            raise InvalidError(f"kind must be one of {ALL_KINDS}")
        with self.connect() as conn:
            rows = _rows(
                conn,
                "SELECT id, slug, title, kind, kind_fixed, fields, created_at,"
                f" updated_at, due, priority, snoozed_until, task_done, task_total,"
                f" {THUMB} AS thumb"
                " FROM page p WHERE deleted_at IS NULL"
                " AND coalesce(?, kind) = kind"
                " ORDER BY updated_at DESC, id DESC LIMIT ?",
                kind, limit,
            )  # fmt: skip
        return [todo_only({**r, "fields": json.loads(r["fields"])}) for r in rows]

    def page(self, key: str) -> dict[str, Any]:
        """A page with its current revision and its captures and their blobs."""
        with self.connect() as conn:
            return self.page_in(conn, key)

    def page_in(self, conn: sqlite3.Connection, key: str) -> dict[str, Any]:
        """page(), on an open connection (e.g. in the transaction that changed it)."""
        page = dict(self._page_row(conn, key))
        captures = _rows(
            conn,
            "SELECT id, kind, text, url, source, author, created_at,"
            " received_at FROM capture WHERE page_id = ? ORDER BY received_at",
            page["id"],
        )
        for c in captures:
            c["blobs"] = _rows(
                conn,
                "SELECT b.sha256, b.mime, b.size, cb.filename FROM capture_blob cb"
                " JOIN blob b USING (sha256) WHERE capture_id = ? ORDER BY ord",
                c["id"],
            )
            for blob in c["blobs"]:
                blob["ingest"] = self._ingest(conn, c["id"], blob["sha256"])
        tags = [r[0] for r in conn.execute(
            "SELECT tag FROM tag WHERE page_id = ? ORDER BY"  # most used first
            " (SELECT count(*) FROM tag t WHERE t.tag = tag.tag) DESC, tag",
            (page["id"],),
        )]  # fmt: skip
        del page["deleted_at"]
        fields = json.loads(page["fields"])
        removed = sorted(self.removed(conn, page["id"], page["body"]))
        extra = self._enriched(conn, page["id"], page["slug"])
        return todo_only({**page, "fields": fields, "tags": tags, "captures": captures,
                          "removed": removed, **extra})  # fmt: skip

    def _enriched(
        self, conn: sqlite3.Connection, page_id: str, slug: str
    ) -> dict[str, Any]:
        """What Claude added to a page apart from its text: model_tags (the page's
        tags Claude added), related (Claude's picks, pages that picked this one, and
        pages linking here with [[slug]], each once, with via: claude, link or both)
        and enrich (its job's state and the summary), None if never asked and off."""
        model_tags = [r[0] for r in conn.execute(
            "SELECT m.tag FROM model_tag m JOIN tag t USING (page_id, tag)"
            " WHERE m.page_id = ? AND m.state = 'on'", (page_id,),
        )]  # fmt: skip
        picks = _rows(
            conn,
            "SELECT p.id, p.slug, p.title, p.kind FROM ("
            " SELECT other_id AS id, rank FROM related WHERE page_id = ?"
            " UNION ALL SELECT page_id, rank + 100 FROM related WHERE other_id = ?"
            ") r JOIN page p ON p.id = r.id WHERE p.deleted_at IS NULL"
            " GROUP BY p.id ORDER BY min(r.rank) LIMIT 8",
            page_id,
            page_id,
        )
        related = {r["id"]: {**r, "via": "claude"} for r in picks}
        for b in self._backlinks(conn, slug):
            if b["id"] in related:
                related[b["id"]]["via"] = "both"
            else:
                related[b["id"]] = {**b, "via": "link"}
        job = conn.execute(
            "SELECT state, last_error, reason FROM enrich_job WHERE page_id = ?"
            " ORDER BY id DESC LIMIT 1",
            (page_id,),
        ).fetchone()
        done = conn.execute(
            "SELECT summary, producer, source, source_title, updated_at"
            " FROM enrichment WHERE page_id = ?",
            (page_id,),
        ).fetchone()
        enrich = None
        if job or done or enrich_on():
            state = job and {"running": "processing", "dead": "failed"}.get(
                job["state"], job["state"]
            )
            enrich = {
                "on": enrich_on(),
                "state": state,  # None: never queued
                "error": job and job["state"] == "dead" and job["last_error"] or None,
                "summary": done and done["summary"] or None,
                "producer": done and done["producer"],
                "source": done and done["source"],
                "at": done and done["updated_at"],
            }
        return {"model_tags": model_tags, "related": list(related.values()),
                "enrich": enrich}  # fmt: skip

    def removed(self, conn: sqlite3.Connection, page_id: str, body: str) -> set[str]:
        """The files an earlier revision of a page's text referred to and its text no
        longer does: their embeds were deleted, so the page no longer shows them (a
        photo of a page made before photos were embedded still is)."""
        earlier: set[str] = set()
        for (text,) in conn.execute(
            "SELECT body FROM page_rev WHERE page_id = ?", (page_id,)
        ):
            earlier |= body_refs(text)
        return earlier - body_refs(body)

    def blob_uses(self, sha: str, page: str) -> int:
        """How many pages other than page (an id) show a stored file, by its embed or
        as a file of their own; the trash left out. NotFoundError if not stored."""
        if not SHA256.fullmatch(sha):
            raise NotFoundError(sha)
        with self.connect() as conn:
            stored = "SELECT 1 FROM blob WHERE sha256 = ?"
            if not conn.execute(stored, (sha,)).fetchone():
                raise NotFoundError(sha)
            return conn.execute(
                "SELECT count(*) FROM page p WHERE p.deleted_at IS NULL AND p.id <> ?"
                " AND (instr(p.body, '/api/blobs/' || ?) OR EXISTS (SELECT 1 FROM"
                " capture c JOIN capture_blob cb ON cb.capture_id = c.id"
                " WHERE c.page_id = p.id AND cb.sha256 = ?))",
                (page, sha, sha),
            ).fetchone()[0]

    def _ingest(
        self, conn: sqlite3.Connection, cid: str, sha: str
    ) -> dict[str, Any] | None:
        """A photo's ingest state and current results; None if it was never queued."""
        job = conn.execute(
            "SELECT state, failures, last_error,"
            " (SELECT paused_until > ? FROM queue_state) AS paused"
            " FROM job WHERE capture_id = ? AND source_sha256 = ?"
            " ORDER BY id DESC LIMIT 1",
            (now(), cid, sha),
        ).fetchone()
        if job is None:
            return None
        state = {"running": "processing", "dead": "failed"}.get(job[0], job[0])
        if state == "queued" and job["paused"]:
            state = "paused"
        current = {
            row["kind"]: row
            for row in conn.execute(
                "SELECT id, kind, version, producer, text, data,"
                " json_extract(data, '$.width') AS width,"
                " json_extract(data, '$.height') AS height FROM derived"
                " WHERE capture_id = ? AND source_sha256 = ? AND superseded_at IS NULL",
                (cid, sha),
            )
        }
        ocr, about, drawing = (current.get(k) for k in KINDS_SHOWN)
        return {
            "state": state,
            "failures": job["failures"],
            "error": job["last_error"],
            "text": ocr and ocr["text"],
            "description": about and about["text"],
            "image_kind": about and json.loads(about["data"] or "{}").get("kind"),
            "drawing": drawing
            and {
                "id": drawing["id"],
                "version": drawing["version"],
                "producer": drawing["producer"],
                "width": drawing["width"],  # its frame: the photo as sent to Claude
                "height": drawing["height"],
            },
        }

    def update_page(
        self,
        key: str,
        base_rev: int | None,
        title: str | None,
        body: str | None,
        author: str,
        kind: str | None = None,
        fields: dict[str, Value | None] | None = None,
        tags: list[str] | None = None,
        todo: dict[str, str | None] | None = None,
        source: str = "web",
        tags_shown: list[str] | None = None,
    ) -> dict[str, Any]:
        """Change a page's title and/or body, refusing an edit of a stale revision;
        and/or its kind (the user's choice, which ingest then keeps), fields and tags
        (all of them: these replace the page's); and/or a todo's due date and priority
        (those given; None clears one). A change of kind or tags is a metadata
        revision (page_meta_rev) by author from source. tags_shown, if given, are the
        tags the editor started from: a tag Claude added since (not among them) is
        kept, not retired."""
        if kind not in (None, *KINDS):
            raise InvalidError(f"kind must be one of {KINDS}")
        tags = None if tags is None else clean_tags(tags)
        shown = None if tags_shown is None else clean_tags(tags_shown)
        todo = {k: check_todo(k, v) for k, v in (todo or {}).items() if k in TODO}
        with self.connect() as conn, transaction(conn):
            page = self._page_row(conn, key)
            before = self._meta(conn, page["id"])
            if kind is not None or fields:
                self._set_kind(conn, page, kind, fields or {})
            if todo:  # as status: not a revision, nor a change to updated_at
                self._set_todo(conn, page["id"], kind or page["kind"], todo)
            if tags is not None:  # not a revision, nor a change to updated_at
                spare: list[str] = []  # Claude's, kept but past MAX_TAGS: not retired
                if shown is not None:  # Claude's tags added after the editor opened
                    tags += self._model_tags_since(conn, page["id"], shown + tags)
                    tags, spare = tags[:MAX_TAGS], tags[MAX_TAGS:]
                conn.execute("DELETE FROM tag WHERE page_id = ?", (page["id"],))
                conn.executemany(
                    "INSERT INTO tag VALUES (?, ?)", [(page["id"], t) for t in tags]
                )
                self._model_tags(conn, page["id"], tags, spare)
            if tags is not None or (fields and "summary" in fields):  # indexed
                self.reindex(conn, page["id"])
            if kind is not None or tags is not None:  # before text: see _record_meta
                after = self._meta(conn, page["id"])
                now_fields = json.loads(conn.execute(
                    "SELECT fields FROM page WHERE id = ?", (page["id"],)
                ).fetchone()[0])  # fmt: skip
                was, sent = json.loads(page["fields"]), fields or {}
                added = {
                    k: v
                    for k, v in now_fields.items()
                    if k not in was and k not in sent
                }  # a new kind's defaults
                self._record_meta(
                    conn, page["id"], author, source, before, after, added
                )
            if title is None and body is None:
                return self.page_in(conn, page["id"])
            if page["rev"] != base_rev:
                raise ConflictError(page["rev"])
            if (
                title is not None
                and " ".join(title.split())
                == conn.execute(
                    "SELECT title FROM page_rev WHERE page_id = ? AND rev = ?",
                    (page["id"], base_rev),
                ).fetchone()[0]
            ):
                title = None  # unchanged since base_rev: keep a newer (model) title
            new_title = page["title"] if title is None else " ".join(title.split())
            new_body: str = (
                page["body"] if body is None else check_page(lines(body), page["body"])
            )
            if not new_title:
                raise InvalidError("title must not be empty")
            if (new_title, new_body) != (page["title"], page["body"]):
                stamp = now()
                conn.execute(
                    "UPDATE page SET title = ?, body = ?, updated_at = ? WHERE id = ?",
                    (new_title, new_body, stamp, page["id"]),
                )
                conn.execute(
                    "INSERT INTO page_rev VALUES (?, ?, ?, ?, ?, ?)",
                    (page["id"], page["rev"] + 1, new_title, new_body, author, stamp),
                )
                self._body(
                    conn,
                    page["id"],
                    boxes_before(page),
                    status_set=bool(fields and "status" in fields),
                )
                self.reindex(conn, page["id"])
                if enrich_on() and should_enrich(
                    conn, page["id"]
                ):  # again once edits stop
                    queue_enrich(conn, page["id"], "save", debounce())
            return self.page_in(conn, page["id"])

    def _model_tags_since(
        self, conn: sqlite3.Connection, page_id: str, known: list[str]
    ) -> list[str]:
        """The page's tags from Claude, 'on', that are not in known: added while a tag
        editor that did not show them was open (so the user has not taken them off)."""
        return [r[0] for r in conn.execute(
            "SELECT m.tag FROM model_tag m JOIN tag t USING (page_id, tag)"
            " WHERE m.page_id = ? AND m.state = 'on'"
            " AND m.tag NOT IN (SELECT value FROM json_each(?)) ORDER BY t.rowid",
            (page_id, json.dumps(known)),
        )]  # fmt: skip

    def _model_tags(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        tags: list[str],
        spare: list[str] | None = None,
    ) -> None:
        """After the user set a page's tags: a tag of Claude's they took off is 'off'
        (Claude never adds it back), one in spare (not taken off, just no room) is
        not; one they put back is theirs from now on."""
        conn.execute(
            "UPDATE model_tag SET state = 'off' WHERE page_id = ? AND state = 'on'"
            " AND tag NOT IN (SELECT value FROM json_each(?))",
            (page_id, json.dumps([*tags, *(spare or [])])),
        )
        conn.execute(
            "DELETE FROM model_tag WHERE page_id = ? AND state = 'off'"
            " AND tag IN (SELECT value FROM json_each(?))",
            (page_id, json.dumps(tags)),
        )

    def _body(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        before: tuple[int, int] = (0, 0),
        follow: bool = True,
        status_set: bool = False,
    ) -> None:
        """After a page's text is written (before: its task boxes, ticked and in
        all, as they were: boxes_before): its boxes counted. With follow, a note
        nobody filed (kind_fixed 0) that has boxes becomes a todo, and a todo's
        status follows them: all ticked, when they were not, is done; one unticked,
        or a new unticked one, when all were reopens a done one. Ticking a page done
        by hand changes no box, a cancelled one is left as it is, a status set in
        the same edit (status_set) wins, and none of it is a revision."""
        row = conn.execute(
            "SELECT body, kind, kind_fixed, fields FROM page WHERE id = ?", (page_id,)
        ).fetchone()
        done, total = tasks(row["body"])
        conn.execute(
            "UPDATE page SET task_done = ?, task_total = ? WHERE id = ?",
            (done, total, page_id),
        )
        if not follow or not total:
            return
        kind, fields = row["kind"], json.loads(row["fields"])
        if kind == "note" and not row["kind_fixed"]:  # filed by its boxes, not fixed
            kind, fields = "todo", {**fields_for("todo", None), **fields}
        if kind != "todo":
            return
        was_all = before[1] > 0 and before[0] == before[1]
        status = fields.get("status", "open")
        if status_set:  # the user's own, in this edit: the boxes don't override it
            pass
        elif done == total and not was_all and status not in ("done", "cancelled"):
            fields["status"] = "done"
        elif was_all and done < total and status == "done":
            fields["status"] = "open"
        conn.execute(
            "UPDATE page SET kind = ?, fields = ? WHERE id = ?",
            (kind, json.dumps(fields), page_id),
        )

    def _set_kind(
        self,
        conn: sqlite3.Connection,
        page: sqlite3.Row,
        kind: str | None,
        changes: dict[str, Value | None],
    ) -> None:
        """A kind the user chose, fixed so ingest never changes it. A new kind keeps
        every field the page has (a summary, a due date, an imported status: a stray
        tap must lose nothing) and adds its defaults for those it lacks. Then changes to
        the fields (None drops one), at most MAX_FIELDS in all. Neither is a new
        revision, nor moves the page up the recent list."""
        fields = json.loads(page["fields"])
        for name, value in changes.items():
            check_value(name, value)
            if value is None:
                fields.pop(name, None)
            else:
                fields[name] = value
        if len(fields) > MAX_FIELDS:
            raise InvalidError(f"a page has at most {MAX_FIELDS} fields")
        if kind is not None and kind != page["kind"]:
            url = conn.execute(
                "SELECT url FROM capture WHERE page_id = ? AND url IS NOT NULL"
                " ORDER BY received_at LIMIT 1",
                (page["id"],),
            ).fetchone()
            # only defaults the page lacks and has room for: never at the cost of a
            # field it has, nor one this request just dropped
            for name, value in fields_for(kind, url and url[0]).items():
                if name not in fields and name not in changes:
                    if len(fields) < MAX_FIELDS:
                        fields[name] = value
        conn.execute(
            "UPDATE page SET kind = ?, kind_fixed = ?, fields = ? WHERE id = ?",
            (kind or page["kind"], int(kind is not None or page["kind_fixed"]),
             json.dumps(fields), page["id"]),
        )  # fmt: skip

    def _set_todo(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        kind: str,
        todo: dict[str, str | None],
    ) -> None:
        """Set (or clear, None) a todo's due date and/or priority, checked already."""
        if kind != "todo" and any(v is not None for v in todo.values()):
            raise InvalidError("due and priority are for todos")
        sets = ", ".join(f"{k} = ?" for k in todo)  # names from TODO only
        conn.execute(f"UPDATE page SET {sets} WHERE id = ?", (*todo.values(), page_id))

    def delete_page(self, key: str, undo: bool = False) -> None:
        """Move a page to the trash (or back); captures and files stay until a purge."""
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE page SET deleted_at = ? WHERE (id = ? OR slug = ?)"
                f" AND deleted_at IS {'NOT' if undo else ''} NULL",
                (None if undo else now(), key, key),
            )
        if cur.rowcount == 0:
            raise NoSuchPage(key)

    def append(
        self,
        key: str,
        cid: str,
        text: str,
        author: str,
        tags: list[str],
        most: int,
        todo: dict[str, str | None] | None = None,
    ) -> tuple[dict[str, str], bool]:
        """Add text (a capture with id cid, source mcp) to the end of a page Claude
        wrote, and these tags, and set its due date and priority (a todo's; those
        given, None clearing one); a retry with the same cid changes nothing. The
        page's body is then at most most bytes. Returns its reference and whether it
        is new."""
        todo = {k: check_todo(k, v) for k, v in (todo or {}).items() if k in TODO}
        stamp = now()
        with self.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT page_id FROM capture WHERE id = ?", (cid,)
            ).fetchone()
            if row:
                return self._ref(conn, cid, row[0]), False
            page = self._page_row(conn, key)
            if not self.by_claude(conn, page["id"]):
                raise InvalidError("only a page written over MCP can be appended to")
            before = self._meta(conn, page["id"])
            if todo:
                self._set_todo(conn, page["id"], page["kind"], todo)
            body = "\n\n".join(x for x in (page["body"].rstrip(), text) if x)
            if len(body.encode()) > most:
                raise InvalidError(too_big(len(body.encode()), most))
            if text:  # none: only its due date or priority changed (no revision)
                conn.execute(
                    "UPDATE page SET body = ?, updated_at = ? WHERE id = ?",
                    (body, stamp, page["id"]),
                )
                conn.execute(
                    "INSERT INTO page_rev VALUES (?, ?, ?, ?, ?, ?)",
                    (page["id"], page["rev"] + 1, page["title"], body, author, stamp),
                )
                self._body(conn, page["id"], boxes_before(page))
                if enrich_on() and should_enrich(conn, page["id"]):  # as for a save
                    queue_enrich(conn, page["id"], "save", debounce())
            conn.execute(  # the retry key, even with no text
                "INSERT INTO capture VALUES (?, 'note', ?, NULL, ?, ?, ?, ?, ?)",
                (cid, text or None, MCP, author, stamp, stamp, page["id"]),
            )
            conn.executemany(
                "INSERT INTO tag VALUES (?, ?) ON CONFLICT DO NOTHING",
                [(page["id"], t) for t in tags],
            )
            # Its tags, as a revision; not a kind its new task boxes filed it as
            after = before._replace(tags=sorted({*before.tags, *tags}))
            self._record_meta(conn, page["id"], author, MCP, before, after)
            self.reindex(conn, page["id"])
            return self._ref(conn, cid, page["id"]), True

    def by_claude(self, conn: sqlite3.Connection, page_id: str) -> bool:
        """Whether a page was written over MCP (its first capture's source)."""
        row = conn.execute(
            "SELECT source FROM capture WHERE page_id = ?"
            " ORDER BY received_at, id LIMIT 1",
            (page_id,),
        ).fetchone()
        return bool(row) and row[0] == MCP

    def _meta(self, conn: sqlite3.Connection, page_id: str) -> Meta:
        """A page's kind, whether it is fixed, and tags, as page_meta_rev has them."""
        row = conn.execute(
            "SELECT kind, kind_fixed FROM page WHERE id = ?", (page_id,)
        ).fetchone()
        tags = conn.execute("SELECT tag FROM tag WHERE page_id = ?", (page_id,))
        return Meta(row[0], row[1], sorted(r[0] for r in tags))

    def _defaults(
        self, conn: sqlite3.Connection, page_id: str, kind: str, fields: dict[str, Any]
    ) -> dict[str, Value]:
        """The fields a page gets on becoming kind: that kind's defaults it lacks."""
        url = conn.execute(
            "SELECT url FROM capture WHERE page_id = ? AND url IS NOT NULL"
            " ORDER BY received_at LIMIT 1",
            (page_id,),
        ).fetchone()
        defaults = fields_for(kind, url and url[0])
        room = max(0, MAX_FIELDS - len(fields))  # a full page gets fewer, or none
        missing = {k: v for k, v in defaults.items() if k not in fields}
        return dict(list(missing.items())[:room])

    def _record_meta(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        author: str,
        source: str,
        before: Meta,
        after: Meta,
        added: dict[str, Value] | None = None,
        reverts: int | None = None,
        batch: str | None = None,
    ) -> int | None:
        """Record a change to a page's kind and tags (and the default fields a new
        kind added), returning its revision's id; none, no revision (a revert always
        is one). Coalesced: a change by the same author and source within
        self.window seconds of the page's latest revision being made folds into it
        (its after becomes this one's), as long as nothing else changed them between
        (that revision's after is this one's before); a fold that leaves it changing
        nothing drops it. A revert, or a change in a batch, never folds into another
        nor is folded into. Kinds that follow a page's text (task boxes file a note as
        a todo) and what ingest sets are not revisions: they are derived."""
        added = added or {}
        if reverts is None and before == after and not added:
            return None
        if source not in META_SOURCES:
            raise InvalidError(f"source must be one of {META_SOURCES}")
        stamp = now()
        last = conn.execute(
            f"{META_REV} WHERE page_id = ? ORDER BY id DESC LIMIT 1", (page_id,)
        ).fetchone()
        if (
            reverts is None
            and batch is None
            and last is not None
            and last["reverts"] is None
            and last["batch_id"] is None
            and (last["author"], last["source"]) == (author, source)
            and meta_of(last, "after") == before
            and 0 <= seconds_between(last["created_at"], stamp) < self.window
        ):
            merged = {**json.loads(last["fields_added"]), **added}
            if meta_of(last, "before") == after and not merged:  # nothing, in all
                conn.execute("DELETE FROM page_meta_rev WHERE id = ?", (last["id"],))
                return None
            conn.execute(
                "UPDATE page_meta_rev SET kind_after = ?, fixed_after = ?,"
                " tags_after = ?, fields_added = ?, updated_at = ? WHERE id = ?",
                (after.kind, after.fixed, json.dumps(after.tags), json.dumps(merged),
                 stamp, last["id"]),
            )  # fmt: skip
            return last["id"]
        cur = conn.execute(
            "INSERT INTO page_meta_rev (page_id, author, source, kind_before,"
            " kind_after, fixed_before, fixed_after, tags_before, tags_after,"
            " fields_added, reverts, batch_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (page_id, author, source, before.kind, after.kind, before.fixed,
             after.fixed, json.dumps(before.tags), json.dumps(after.tags),
             json.dumps(added), reverts, batch, stamp, stamp),
        )  # fmt: skip
        return cur.lastrowid

    def _plan(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        before: Meta,
        after: Meta,
        drop: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Value], dict[str, Any]]:
        """A page's fields once given after's kind: with the defaults a new kind adds
        (as the PWA's kind picker), and without those of drop that still hold the
        value it gives (a revert takes off what the change it undoes added, unless
        changed since). Returns the fields, those added and those removed."""
        row = conn.execute("SELECT fields FROM page WHERE id = ?", (page_id,))
        fields = json.loads(row.fetchone()[0])
        added = {}
        if after.kind != before.kind:
            added = self._defaults(conn, page_id, after.kind, fields)
        dropped = {
            k: v for k, v in (drop or {}).items() if fields.get(k) == v
        }  # fmt: skip
        fields = {k: v for k, v in {**fields, **added}.items() if k not in dropped}
        if len(fields) > MAX_FIELDS:
            raise InvalidError(f"a page has at most {MAX_FIELDS} fields")
        return fields, added, dropped

    def _put_meta(
        self,
        conn: sqlite3.Connection,
        page_id: str,
        before: Meta,
        after: Meta,
        author: str,
        source: str,
        reverts: int | None = None,
        batch: str | None = None,
        drop: dict[str, Any] | None = None,
    ) -> tuple[int | None, dict[str, Value], dict[str, Any]]:
        """Give a page after's kind (with its fields: _plan), fixed or not, and tags,
        as a revision; its search chunk again. Returns the revision's id and the
        fields added and removed."""
        fields, added, dropped = self._plan(conn, page_id, before, after, drop)
        conn.execute(
            "UPDATE page SET kind = ?, kind_fixed = ?, fields = ? WHERE id = ?",
            (after.kind, after.fixed, json.dumps(fields), page_id),
        )
        if after.tags != before.tags:
            conn.execute("DELETE FROM tag WHERE page_id = ?", (page_id,))
            conn.executemany(
                "INSERT INTO tag VALUES (?, ?)", [(page_id, t) for t in after.tags]
            )
            self._model_tags(conn, page_id, after.tags)  # as a PWA tag save
            self.reindex(conn, page_id)
        revision = self._record_meta(
            conn, page_id, author, source, before, after, added, reverts, batch
        )
        return revision, added, dropped

    @staticmethod
    def _change(
        page: sqlite3.Row,
        before: Meta,
        after: Meta,
        revision: int | None,
        added: dict[str, Any],
        dropped: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """What a metadata edit did (or, in a dry run, would do) to a page."""
        return {
            "id": page["id"], "slug": page["slug"], "title": page["title"],
            "changed": before != after or bool(added or dropped),
            "revision": revision,
            "kind_before": before.kind, "kind_after": after.kind,
            "fixed_before": bool(before.fixed), "fixed_after": bool(after.fixed),
            "tags_before": before.tags, "tags_after": after.tags,
            "tags_added": [t for t in after.tags if t not in before.tags],
            "tags_removed": [t for t in before.tags if t not in after.tags],
            "fields_added": added, "fields_removed": dropped or {},
        }  # fmt: skip

    def _apply(
        self,
        conn: sqlite3.Connection,
        page: sqlite3.Row,
        before: Meta,
        after: Meta,
        author: str,
        source: str,
        dry_run: bool,
        batch: str | None,
        reverts: int | None = None,
        drop: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """One page's metadata change, or with dry_run what it would be."""
        if dry_run:
            _, added, dropped = self._plan(conn, page["id"], before, after, drop)
            return self._change(page, before, after, None, added, dropped)
        revision, added, dropped = self._put_meta(
            conn, page["id"], before, after, author, source, reverts, batch, drop
        )
        out = self._change(page, before, after, revision, added, dropped)
        return {**out, "batch": batch if revision else None}

    def edit_meta(
        self,
        keys: list[str],
        author: str,
        source: str,
        kind: str | None = None,
        add: list[str] | None = None,
        remove: list[str] | None = None,
        tags: list[str] | None = None,
        dry_run: bool = False,
        batch: bool = False,
    ) -> dict[str, Any]:
        """Set the kind of these pages (ids or slugs; fixed, as the PWA's picker
        does, even if it is theirs already) and/or change their tags: add and remove
        these (exact tags: removing a leaves a/b), or replace them all with tags. Each
        page changed is a revision (see _record_meta); with batch (a query's pages,
        however many) or several distinct pages, all of them share a batch id,
        returned, which revert_batch undoes at once. updated_at stays as it was, as
        for the PWA's tag and kind edits. All or nothing: an unknown page or a
        refused change saves none. dry_run: say what would change, save nothing.
        Never the title, the text or other fields."""
        kind = KIND_NAMES.get(kind, kind) if kind is not None else None
        if kind not in (None, *KINDS):
            raise InvalidError(f"kind must be one of {KINDS}")
        add, remove = clean_tags(add or []), clean_tags(remove or [])
        if tags is not None and (add or remove):
            raise InvalidError("give tags to replace them all, or tags to add/remove")
        if set(add) & set(remove):
            raise InvalidError("a tag cannot be both added and removed")
        tags = None if tags is None else clean_tags(tags)
        out: list[dict[str, Any]] = []
        with self.connect() as conn, transaction(conn):
            pages: dict[str, sqlite3.Row] = {}
            for key in keys:  # each page once, however named
                page = self._page_row(conn, key)
                pages.setdefault(page["id"], page)
            several = batch or len(pages) > 1
            batch_id = new_ulid() if several and not dry_run else None
            for page in pages.values():
                before = self._meta(conn, page["id"])
                new = tags if tags is not None else [
                    t for t in before.tags if t not in remove
                ] + add  # fmt: skip
                after = Meta(
                    kind or before.kind, 1 if kind else before.fixed, sorted(set(new))
                )
                if len(after.tags) > MAX_TAGS:
                    raise InvalidError(f"{page['slug']}: over {MAX_TAGS} tags")
                out.append(self._apply(
                    conn, page, before, after, author, source, dry_run, batch_id
                ))  # fmt: skip
        changed = any(c["revision"] for c in out)
        return {"batch": batch_id if changed else None, "pages": out}

    def rename_tag(
        self,
        old: str,
        new: str,
        author: str,
        source: str,
        dry_run: bool = False,
        limit: int = 50,
        merge: bool = False,
    ) -> dict[str, Any]:
        """Rename a tag on every page with it (not the trash's), and the tags under it
        (old/x becomes new/x), as one batch (see edit_meta). Refused: more than limit
        pages, a new name under the old one, and, unless merge, a new name already in
        use (a merge cannot be undone by renaming back: only by reverting the batch).
        dry_run: say what would change, save nothing."""
        old, new = clean_tags([old])[0], clean_tags([new])[0]
        if old == new:
            raise InvalidError("the new name is the old one")
        if new.startswith(f"{old}/"):
            raise InvalidError(f"{new!r} is under {old!r}: it would nest again")

        def renamed(tag: str) -> str:
            if tag == old or tag.startswith(f"{old}/"):
                tag = new + tag[len(old) :]
            if len(tag) > MAX_TAG:
                raise InvalidError(f"a tag must be 1 to {MAX_TAG} characters: {tag!r}")
            return tag

        under = (
            "SELECT DISTINCT t.page_id FROM tag t JOIN page p ON p.id = t.page_id"
            " WHERE p.deleted_at IS NULL AND (t.tag = ? OR substr(t.tag, 1, ?) = ?)"
            " ORDER BY t.page_id"
        )
        batch_id = None if dry_run else new_ulid()
        out: list[dict[str, Any]] = []
        with self.connect() as conn, transaction(conn):
            ids = [r[0] for r in conn.execute(under, (old, len(old) + 1, f"{old}/"))]
            if len(ids) > limit:
                raise InvalidError(
                    f"{old!r} is on {len(ids)} pages, more than {limit}: raise limit"
                )
            in_use = (  # the trash's too: restoring a page would merge them unasked
                "SELECT 1 FROM tag WHERE tag = ? OR substr(tag, 1, ?) = ? LIMIT 1"
            )
            if (
                not merge
                and conn.execute(in_use, (new, len(new) + 1, f"{new}/")).fetchone()
            ):
                raise InvalidError(
                    f"{new!r} is in use (perhaps only in the trash): renaming into it"
                    " merges the two (merge)"
                )
            for page_id in ids:
                page = self._page_row(conn, page_id)
                before = self._meta(conn, page_id)
                after = before._replace(tags=sorted({renamed(t) for t in before.tags}))
                out.append(self._apply(
                    conn, page, before, after, author, source, dry_run, batch_id
                ))  # fmt: skip
        changed = any(c["revision"] for c in out)
        return {"batch": batch_id if changed else None, "pages": out}

    def revert_meta(
        self, revision: int, author: str, source: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """Undo a metadata revision: give its page back the kind (fixed or not) and
        tags it had just before it, so undoing later ones too, and take off the
        default fields its kind change added (those not changed since). The revert is
        a revision of its own, never folded into another, so it can be undone in
        turn: nothing is lost. No revision (None) if the page has them already.
        dry_run: save nothing."""
        with self.connect() as conn, transaction(conn):
            row = conn.execute(f"{META_REV} WHERE id = ?", (revision,)).fetchone()
            if row is None:
                raise NoSuchRevision(f"revision {revision}")
            page = self._page_row(conn, row["page_id"])  # not in the trash
            out = self._revert(conn, page, row, author, source, dry_run, None)
            return {**out, "reverts": revision}

    def _revert(
        self,
        conn: sqlite3.Connection,
        page: sqlite3.Row,
        row: sqlite3.Row,
        author: str,
        source: str,
        dry_run: bool,
        batch: str | None,
    ) -> dict[str, Any]:
        before, after = self._meta(conn, page["id"]), meta_of(row, "before")
        drop = json.loads(row["fields_added"])
        _, added, dropped = self._plan(conn, page["id"], before, after, drop)
        if dry_run or (before == after and not added and not dropped):
            return self._change(page, before, after, None, added, dropped)
        return self._apply(
            conn, page, before, after, author, source, False, batch, row["id"], drop
        )

    def revert_batch(
        self, batch: str, author: str, source: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """Undo every revision of a batch (an edit_meta or rename_tag of several
        pages, or a batch revert) at once: as revert_meta, page by page, as a new
        batch, itself undoable at once. Refused, saving nothing, if any page's kind
        or tags changed since (conflicts; revert those pages' revisions one by one);
        pages in the trash are skipped. dry_run: say what would change, and which
        pages conflict, and save nothing."""
        with self.connect() as conn, transaction(conn):
            rows = conn.execute(
                f"{META_REV} WHERE batch_id = ? ORDER BY id", (batch,)
            ).fetchall()
            if not rows:
                raise NoSuchRevision(f"batch {batch}")
            pages, skipped, conflicts = [], [], []
            for row in rows:
                try:
                    page = self._page_row(conn, row["page_id"])
                except NotFoundError:
                    skipped.append({"id": row["page_id"], "revision": row["id"]})
                    continue
                if self._meta(conn, page["id"]) != meta_of(row, "after"):
                    conflicts.append({
                        "id": page["id"], "slug": page["slug"], "revision": row["id"],
                    })  # fmt: skip
                pages.append((page, row))
            if conflicts and not dry_run:
                slugs = ", ".join(c["slug"] for c in conflicts)
                raise InvalidError(
                    f"changed since batch {batch}, so nothing was reverted: {slugs}"
                    " (revert those pages' revisions one by one)"
                )
            new = None if dry_run else new_ulid()
            out = [
                {**self._revert(conn, p, r, author, source, dry_run, new),
                 "reverts": r["id"]}
                for p, r in pages
            ]  # fmt: skip
        changed = any(c.get("revision") for c in out)
        return {
            "batch": new if changed else None, "reverts_batch": batch, "pages": out,
            "skipped": skipped, "conflicts": conflicts,
        }  # fmt: skip

    def revisions(
        self, key: str | None = None, limit: int = 20, batch: str | None = None
    ) -> dict[str, Any]:
        """A page's history, newest first: its metadata revisions (kind, fixed or
        not, and tags, before and after, each with who made it, when, and its batch)
        and its text revisions (page_rev: rev, title, author, when and size, not the
        text). With batch, only that batch's revisions, of every page (with key, of
        that page)."""
        with self.connect() as conn:
            page = self._page_row(conn, key) if key else None
            where, args = [], []
            if page is not None:
                where.append("page_id = ?")
                args.append(page["id"])
            if batch is not None:
                where.append("batch_id = ?")
                args.append(batch)
            if not where:
                raise InvalidError("give a page or a batch")
            meta = conn.execute(
                f"{META_REV} WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
                (*args, limit + 1),
            ).fetchall()
            more, meta = len(meta) > limit, meta[:limit]
            slugs = dict(conn.execute(
                "SELECT id, slug FROM page"
                " WHERE id IN (SELECT value FROM json_each(?))",
                (json.dumps([r["page_id"] for r in meta]),),
            ).fetchall())  # fmt: skip
            text = [] if page is None else _rows(
                conn,
                "SELECT rev, title, author, created_at, length(CAST(body AS BLOB))"
                " AS bytes FROM page_rev WHERE page_id = ? ORDER BY rev DESC LIMIT ?",
                page["id"], limit,
            )  # fmt: skip
        out: dict[str, Any] = {
            "meta": [{**meta_row(r), "slug": slugs.get(r["page_id"])} for r in meta],
            "more": more,  # older revisions than limit allows
            "text": text,
        }
        if page is not None:
            out |= {
                "id": page["id"], "slug": page["slug"], "title": page["title"],
                "kind": page["kind"], "rev": page["rev"],
            }  # fmt: skip
        return out

    def text_revision(self, key: str, rev: int) -> dict[str, Any]:
        """One text revision of a page: its title and body then, who wrote it, when."""
        with self.connect() as conn:
            page = self._page_row(conn, key)
            row = conn.execute(
                "SELECT rev, title, body, author, created_at FROM page_rev"
                " WHERE page_id = ? AND rev = ?",
                (page["id"], rev),
            ).fetchone()
        if row is None:
            raise NoSuchRevision(f"revision {rev} of {key}")
        return dict(row)

    def edit_text(
        self,
        key: str,
        author: str,
        change: Callable[[sqlite3.Connection, sqlite3.Row], tuple[str, str]],
        base_rev: int | None = None,
        dry_run: bool = False,
        fold: bool = True,
    ) -> dict[str, Any]:
        """Change the title and/or body of a page (not one in the trash) as a new
        text revision by author: change(conn, page) gives its new title and body
        from the current ones (raising InvalidError to refuse). Refused
        (ConflictError) if base_rev is given and is not the page's current rev.
        Nothing is written if they are what the page has, nor with dry_run. Returns
        the page's id, slug, rev_before and rev (the new one, or rev_before), the
        title and body before and after, changed, and folded (the revision a burst
        folded into this one, else None). With fold, see _put_text."""
        with self.connect() as conn, transaction(conn):
            page = self._page_row(conn, key)
            if base_rev is not None and base_rev != page["rev"]:
                raise ConflictError(page["rev"])
            title, body = change(conn, page)
            if not title.strip():
                raise InvalidError("title must not be empty")
            body = check_page(lines(body), page["body"])
            changed = (title, body) != (page["title"], page["body"])
            rev, folded = page["rev"], None
            if changed and not dry_run:
                rev, folded = self._put_text(conn, page, title, body, author, fold)
            return {
                "id": page["id"], "slug": page["slug"], "rev_before": page["rev"],
                "rev": rev, "changed": changed, "folded": folded,
                "title_before": page["title"], "title": title,
                "body_before": page["body"], "body": body,
            }  # fmt: skip

    def _put_text(
        self,
        conn: sqlite3.Connection,
        page: sqlite3.Row,
        title: str,
        body: str,
        author: str,
        fold: bool,
    ) -> tuple[int, int | None]:
        """Write a page's new title and body as text revision rev + 1, returning it
        and the revision folded into it (else None).

        Coalescing (fold): if the page's latest text revision is by the same author,
        is not its first, was made within self.window seconds, and does not hold the
        body of an earlier revision (a revert's, which is never folded into, whatever
        its title), the
        burst's text replaces it: that revision goes and this one keeps its
        created_at. The number still moves on (rev + 1, never a number used before),
        since rev is the PWA's edit token: an editor holding the folded revision
        gets a conflict (409), never a silent overwrite. A burst leaves a gap in the
        numbers."""
        stamp = now()
        created, folded = stamp, None
        last = conn.execute(
            "SELECT rev, author, created_at FROM page_rev"
            " WHERE page_id = ? AND rev = ?",
            (page["id"], page["rev"]),
        ).fetchone()
        if (
            fold
            and last is not None
            and last["rev"] > 1
            and last["author"] == author
            and 0 <= seconds_between(last["created_at"], stamp) < self.window
            and not conn.execute(
                "SELECT 1 FROM page_rev r JOIN page_rev l"
                " ON l.page_id = r.page_id AND l.rev = ?"
                " WHERE r.page_id = ? AND r.rev < l.rev"
                " AND r.body = l.body LIMIT 1",
                (last["rev"], page["id"]),
            ).fetchone()
        ):
            conn.execute(
                "DELETE FROM page_rev WHERE page_id = ? AND rev = ?",
                (page["id"], last["rev"]),
            )
            created, folded = last["created_at"], last["rev"]
        rev = page["rev"] + 1
        conn.execute(
            "UPDATE page SET title = ?, body = ?, updated_at = ? WHERE id = ?",
            (title, body, stamp, page["id"]),
        )
        conn.execute(
            "INSERT INTO page_rev VALUES (?, ?, ?, ?, ?, ?)",
            (page["id"], rev, title, body, author, created),
        )
        self._body(conn, page["id"], boxes_before(page))
        self.reindex(conn, page["id"])
        if enrich_on() and should_enrich(conn, page["id"]):  # as for the PWA's saves
            queue_enrich(conn, page["id"], "save", debounce())
        return rev, folded

    def edited_by_claude(self, page_id: str) -> bool:
        """Whether Claude changed a page's text over MCP after it was made (is:
        claude-edited): a text revision of its, after the first."""
        with self.connect() as conn:
            return bool(conn.execute(
                "SELECT 1 FROM page_rev WHERE page_id = ? AND rev > 1 AND author = ?",
                (page_id, CLAUDE),
            ).fetchone())  # fmt: skip

    def text_at(self, conn: sqlite3.Connection, page_id: str, rev: int) -> sqlite3.Row:
        """A page's text revision rev (title, body), or NotFoundError."""
        row = conn.execute(
            "SELECT rev, title, body FROM page_rev WHERE page_id = ? AND rev = ?",
            (page_id, rev),
        ).fetchone()
        if row is None:
            raise NoSuchRevision(f"revision {rev} of {page_id}")
        return row

    def tags_of(self, ids: list[str]) -> dict[str, list[str]]:
        """Each page's tags, most used first: for list rows, which lack them."""
        out: dict[str, list[str]] = {page_id: [] for page_id in ids}
        with self.connect() as conn:
            for page_id, tag in conn.execute(
                "SELECT page_id, tag FROM tag WHERE page_id IN"
                " (SELECT value FROM json_each(?)) ORDER BY"
                " (SELECT count(*) FROM tag t WHERE t.tag = tag.tag) DESC, tag",
                (json.dumps(ids),),
            ):
                out[page_id].append(tag)
        return out

    def images_of(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Each page's images, for list rows: how many (image files of its captures)
        and its first one's SHA-256 and what Claude made of it (its current
        description and kind; None if not read yet). A page with none is left out."""
        out: dict[str, dict[str, Any]] = {}
        with self.connect() as conn:
            for row in conn.execute(
                "WITH image AS (SELECT c.page_id, c.id AS capture_id, cb.sha256,"
                " row_number() OVER (PARTITION BY c.page_id"
                "  ORDER BY c.received_at, cb.ord) AS n,"
                " count(*) OVER (PARTITION BY c.page_id) AS total"
                " FROM capture c JOIN capture_blob cb ON cb.capture_id = c.id"
                " JOIN blob b USING (sha256) WHERE b.mime LIKE 'image/%'"
                " AND c.page_id IN (SELECT value FROM json_each(?)))"
                " SELECT i.page_id, i.total, i.sha256, d.text,"
                " json_extract(d.data, '$.kind') FROM image i LEFT JOIN derived d"
                " ON d.capture_id = i.capture_id AND d.source_sha256 = i.sha256"
                " AND d.kind = 'description' AND d.superseded_at IS NULL"
                " WHERE i.n = 1",
                (json.dumps(ids),),
            ):
                out[row[0]] = {
                    "count": row[1], "sha256": row[2], "description": row[3],
                    "image_kind": row[4],
                }  # fmt: skip
        return out

    def backlinks(self, slug: str) -> list[dict[str, str]]:
        """The pages (not in the trash) whose text links to slug with [[slug]]."""
        with self.connect() as conn:
            return [
                {k: r[k] for k in ("id", "slug", "title")}
                for r in self._backlinks(conn, slug)
            ]

    def _backlinks(self, conn: sqlite3.Connection, slug: str) -> list[dict[str, str]]:
        return _rows(
            conn,
            "SELECT id, slug, title, kind FROM page WHERE deleted_at IS NULL"
            " AND slug <> ? AND (instr(body, '[[' || ? || ']]') > 0"
            " OR instr(body, '[[' || ? || '|') > 0) ORDER BY updated_at DESC",
            slug, slug, slug,
        )  # fmt: skip

    def search(self, query: str, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        """Pages matching a query (see scrap.query): every word somewhere in the page
        (its title, tags, summary, body, or a photo's text or description; each
        word as a prefix), no NOT word anywhere, and all the filters. Ranked by bm25 of
        the page's best chunk, title, tag and summary matches weighing most; a query
        of filters alone lists its pages newest first; sort: orders either its own
        way. offset: skip that many hits (the next page of results)."""
        q = parse(query)
        if not q.terms and not q.filters:
            return []
        where, args = self._where(q)
        # sort: first, then the default order (a page's chunks share its sort key, so
        # its best chunk still comes first). Pages with no due date or priority last.
        order = ""
        if q.sort:
            key, desc = q.sort
            way = "DESC" if desc else "ASC"
            order = f"{SORT_SQL[key]} {way} NULLS LAST, p.id {way}, "
        hits: dict[str, dict[str, Any]] = {}  # a page once, at its best chunk
        with self.connect() as conn:
            if q.positive:  # bm25() and snippet() refuse GROUP BY: group here instead
                # First the pages with every word in the title, then those with every
                # word in the title, tags or summary: bm25 alone lets a short body
                # that says a word twice beat a long page tagged with it
                every = " AND ".join(q.fts(t) for t in q.positive)
                tier = " c.id IN (SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ?)"
                rows = conn.execute(
                    "SELECT p.id, p.slug, p.title, p.kind, p.fields, p.due, p.priority,"
                    " p.snoozed_until, p.task_done, p.task_total,"
                    " snippet(chunk_fts, 3, char(2), char(3), '…', 16) AS snippet"
                    " FROM chunk_fts JOIN chunk c ON c.id = chunk_fts.rowid"
                    " JOIN page p ON p.id = c.page_id"
                    f" WHERE chunk_fts MATCH ? AND {where}"
                    f" ORDER BY {order}{tier} DESC, {tier} DESC,"
                    f" bm25(chunk_fts, {WEIGHTS})",
                    (" OR ".join(q.fts(t) for t in q.positive), *args,
                     f"title : ({every})", f"{{title tags summary}} : ({every})"),
                )  # fmt: skip
            else:
                rows = conn.execute(
                    "SELECT p.id, p.slug, p.title, p.kind, p.fields, p.due, p.priority,"
                    " p.snoozed_until, p.task_done, p.task_total, p.body AS snippet"
                    f" FROM page p WHERE {where}"
                    f" ORDER BY {order}p.updated_at DESC, p.id DESC LIMIT ? OFFSET ?",
                    (*args, limit, offset),
                )
                offset = 0  # done by SQL
            for row in rows:
                hits.setdefault(row["id"], dict(row))
                if len(hits) == offset + limit:
                    break
            hits = dict(list(hits.items())[offset:])
            # Each hit's thumbnail and last edit, as /api/pages has them: one query
            for row in conn.execute(
                f"SELECT p.id, p.updated_at, {THUMB} AS thumb FROM page p"
                " WHERE p.id IN (SELECT value FROM json_each(?))",
                (json.dumps(list(hits)),),
            ):
                hits[row["id"]] |= {"updated_at": row[1], "thumb": row[2]}
        for hit in hits.values():  # HTML-safe, with matches in <mark>
            hit["fields"] = json.loads(hit["fields"])
            todo_only(hit)
            if not q.positive:  # no match to show: its summary, else its start
                summary = hit["fields"].get("summary")
                text = summary if isinstance(summary, str) else unlink(hit["snippet"])
                hit["snippet"] = " ".join(CONTROL.sub(" ", text).split()[:24])
            snippet = html.escape(hit["snippet"])
            hit["snippet"] = snippet.replace("\x02", "<mark>").replace(
                "\x03", "</mark>"
            )
        return list(hits.values())

    def facets(self, query: str, top: int = 12) -> dict[str, Any]:
        """What the pages a query matches have in common, to narrow it with a tap: how
        many there are, their kinds, their most used tags (a/b counts for a too) and
        how many are personal or work; and the query's filters, as typed."""
        q = parse(query)
        out: dict[str, Any] = {
            "total": 0, "kinds": [], "tags": [], "personal": {"work": 0, "personal": 0},
            "active": [{"token": f.token, "key": f.key, "value": f.value, "neg": f.neg}
                       for f in q.filters],
        }  # fmt: skip
        if not q.terms and not q.filters:
            return out
        where, args = self._where(q)
        with self.connect() as conn:
            ids = json.dumps([r[0] for r in conn.execute(
                f"SELECT p.id FROM page p WHERE {where}", args
            )])  # fmt: skip
            pages = "(SELECT value FROM json_each(?))"
            out["kinds"] = [list(r) for r in conn.execute(
                f"SELECT kind, count(*) AS n FROM page WHERE id IN {pages}"
                " GROUP BY kind ORDER BY n DESC, kind", (ids,),
            )]  # fmt: skip
            personal = conn.execute(
                "SELECT count(*), coalesce(sum(json_extract(fields, '$.personal') = 1),"
                f" 0) FROM page WHERE id IN {pages}",
                (ids,),
            ).fetchone()
            tags = conn.execute(
                f"SELECT page_id, tag FROM tag WHERE page_id IN {pages}", (ids,)
            ).fetchall()
        total = personal[0]
        out["total"] = total
        out["personal"] = {"work": total - personal[1], "personal": personal[1]}
        counts = tag_counts(tags)
        chosen = [f.value for f in q.filters if f.key == "tag" and not f.neg]
        ranked = sorted(
            ((tag, n) for tag, n in counts.items()
             if tag not in chosen and (n < total or total == 1)),
            key=lambda t: (-t[1], t[0]),
        )  # fmt: skip
        out["tags"] = [list(t) for t in ranked[:top]]
        return out

    def tags(self) -> list[list[Any]]:
        """Every tag on a page (not in the trash), a/b's parent a too, with how many
        pages have it (a: those with a or a/anything) and how many have that very tag
        (0 for a parent nobody gave a page), in order."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT page_id, tag FROM tag JOIN page p ON p.id = tag.page_id"
                " WHERE p.deleted_at IS NULL"
            ).fetchall()
        own = Counter(tag for _, tag in rows)
        return [[t, n, own[t]] for t, n in sorted(tag_counts(rows).items())]

    def _where(self, q: Query) -> tuple[str, list[Any]]:
        """SQL conditions on page p for a query's words and filters, and their args."""
        sql, args = ["p.deleted_at IS NULL"], []
        in_page = (
            "p.id {} IN (SELECT c.page_id FROM chunk_fts JOIN chunk c"
            " ON c.id = chunk_fts.rowid WHERE chunk_fts MATCH ?)"
        )
        for term in q.terms:
            sql.append(in_page.format("NOT" if term.neg else ""))
            args.append(q.fts(term))
        kinds = [KIND_NAMES.get(f.value, f.value) for f in q.filters
                 if f.key == "kind" and not f.neg]  # fmt: skip
        if kinds:  # a page has one kind: two kinds mean either
            sql.append("p.kind IN (SELECT value FROM json_each(?))")
            args.append(json.dumps(kinds))
        priorities = [f.value for f in q.filters if f.key == "priority" and not f.neg]
        if priorities:  # one each, as kinds: priority:high priority:medium is either
            sql.append(f"{TODO_SQL}{RANK} IN (SELECT value FROM json_each(?))")
            args.append(json.dumps([PRIORITY_NAMES.get(v, v) for v in priorities]))
        dated = "created_at" if ("date", "created") in [
            (f.key, f.value) for f in q.filters if not f.neg
        ] else "updated_at"  # fmt: skip
        for f in q.filters:
            no = "NOT " if f.neg else ""
            if f.key in ("after", "before"):  # UTC: see query.bound
                cut = bound(f.key, f.value)
                op = ">=" if f.key == "after" else "<"
                # not a date or a time ago: nothing (and with -, everything)
                sql.append(f"{no}(p.{dated} {op} ?)" if cut else f"{no}0")
                args.extend([cut] if cut else [])
            elif f.key == "kind" and f.neg:
                sql.append("p.kind <> ?")
                args.append(KIND_NAMES.get(f.value, f.value))
            elif f.key == "tag":  # whole segments: tag:b finds a/b, tag:a finds a/b
                sql.append(
                    f"{no}EXISTS (SELECT 1 FROM tag t WHERE t.page_id = p.id"
                    " AND instr('/' || t.tag || '/', ?) > 0)"
                )
                args.append(f"/{f.value.strip('/')}/")
            elif f.key == "has":  # has:image, has:drawing; any other value: nothing
                sql.append(f"{no}{HAS[f.value]}" if f.value in HAS else f"{no}0")
            elif f.key == "image":  # image:photo, image:whiteboard...
                sql.append(f"{no}{IMAGE_KIND}")
                args.append(f.value)
            elif f.key == "is" and f.value == "claude":  # written over MCP
                sql.append(
                    f"{no}EXISTS (SELECT 1 FROM capture c WHERE c.page_id = p.id"
                    " AND c.source = ?)"
                )
                args.append(MCP)
            elif f.key == "is" and f.value == "claude-edited":  # text changed by MCP
                # a text revision by Claude after the first: an edit_page, a
                # revert_text, or an append to a page Claude wrote
                sql.append(
                    f"{no}EXISTS (SELECT 1 FROM page_rev r WHERE r.page_id = p.id"
                    " AND r.rev > 1 AND r.author = ?)"
                )
                args.append(CLAUDE)
            elif f.key == "is" and f.value == "snoozed":  # a todo hidden until later
                # An open one: a done or cancelled one's snooze hides nothing (#131)
                sql.append(
                    f"{no}coalesce({TODO_SQL}p.snoozed_until > ?"
                    " AND coalesce(json_extract(p.fields, '$.status'), 'open')"
                    " NOT IN ('done', 'cancelled'), 0)"
                )
                args.append(date.today().isoformat())  # the server's day, as due:'s
            elif f.key == "is" and f.value in ("personal", "work"):
                want = "IS 1" if f.value == "personal" else "IS NOT 1"
                sql.append(f"{no}(json_extract(p.fields, '$.personal') {want})")
            elif f.key == "sort":  # an order, not a condition: see search()
                continue
            elif f.key == "due":  # a todo's: due:<today, due:2026-11-01, due:none
                asked = due(f.value)
                if asked is None:  # not a day: nothing (and with -, everything)
                    sql.append(f"{no}0")
                elif asked[0] == "none":
                    sql.append(f"{no}coalesce({TODO_SQL}p.due IS NULL, 0)")
                else:  # the operator is one of query.COMPARE's
                    sql.append(f"{no}coalesce({TODO_SQL}p.due {asked[0]} ?, 0)")
                    args.append(asked[1])
            elif f.key == "priority" and f.neg:  # priority:none: a todo with none
                sql.append(f"NOT ({TODO_SQL}{RANK} = ?)")
                args.append(PRIORITY_NAMES.get(f.value, f.value))
            elif f.key == "priority":  # see above: either of them
                continue
            elif f.key == "is":  # a status: is:done, is:open...
                status = "coalesce(json_extract(p.fields, '$.status'), '')"
                sql.append(f"{no}({status} = ?)")
                args.append(f.value.replace(" ", "_"))
        return " AND ".join(sql), args

    def blob(self, sha: str) -> tuple[Path, str]:
        """The path and MIME type of a stored file."""
        if not SHA256.fullmatch(sha):
            raise NotFoundError(sha)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT mime FROM blob WHERE sha256 = ?", (sha,)
            ).fetchone()
        path = self.blob_path(sha)
        if row is None or not path.is_file():
            raise NotFoundError(sha)
        return path, row[0]

    def blob_name(self, sha: str) -> str | None:
        """The name a stored file was uploaded under, if any."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT filename FROM capture_blob WHERE sha256 = ?"
                " AND filename IS NOT NULL LIMIT 1",
                (sha,),
            ).fetchone()
        return row and row[0]
