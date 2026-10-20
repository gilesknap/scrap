"""Storage: one SQLite database and a folder of content-addressed files."""

import fcntl
import hashlib
import html
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
import unicodedata
from collections.abc import Iterator
from contextlib import closing, contextmanager, suppress
from datetime import UTC, datetime
from importlib.resources import files as package_files
from pathlib import Path
from typing import IO, Any

from .markdown import plain
from .query import CONTROL, Query, bound, parse

__all__ = ["Store", "NotFoundError", "ConflictError", "TooLargeError", "InvalidError"]

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
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
# The kinds a user can choose (memory and reference are in the schema, not offered yet),
# and the fields a page gets when it becomes that kind
KINDS = ("note", "todo", "consume", "whiteboard", "document")
DEFAULT_FIELDS = {
    "todo": {"status": "open"},
    "consume": {"subtype": "read", "status": "open"},
}
HINT_FIELDS = DEFAULT_FIELDS  # its older name, used by the importer (#47): remove later
HINTS = ("todo", "consume")  # the older capture field, still accepted
ALL_KINDS = (*KINDS, "memory", "reference")  # in the schema, so a filter may ask
# kind: in a search also takes the PWA's names for kinds
# A page p's thumbnail: the SHA-256 of its first image, if any (SQL, for a column)
THUMB = (
    "(SELECT b.sha256 FROM capture c JOIN capture_blob cb"
    " ON cb.capture_id = c.id JOIN blob b USING (sha256)"
    " WHERE c.page_id = p.id AND b.mime LIKE 'image/%'"
    " ORDER BY c.received_at, cb.ord LIMIT 1)"
)
KIND_NAMES = {"read": "consume", "board": "whiteboard", "doc": "document"}
SOURCES = ("pwa", "share", "mcp")
MAX_FIELDS = 32  # a page's fields are listed with every page: keep them small
KINDS_SHOWN = ("ocr", "description", "excalidraw")
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


def unlink(text: str) -> str:
    """Markdown text with each link or image reduced to its label, and a page link to
    its label (else slug): addresses are not words to search for. Not handled:
    reference definitions ([r]: url), link text holding brackets, a URL with
    parentheses (leaves a ")"), and code (unlinked too)."""
    text = WIKI_LINK.sub(lambda m: m[2] or m[1], text)
    return MD_LINK.sub(r"\1", text)


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
    summary = summary if isinstance(summary, str) else ""
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


def index_all(conn: sqlite3.Connection) -> None:
    """Every page's own chunk again (the trash's too: undo brings a page back)."""
    for (page_id,) in conn.execute("SELECT id FROM page").fetchall():
        index_page(conn, page_id)


AFTER = {3: index_all, 4: index_all}  # migration number -> its Python step


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
            if not dest.exists():
                with suppress(FileExistsError):  # the same bytes, saved concurrently
                    os.link(tmp.name, dest)
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
        if not url and text and BARE_URL.fullmatch(text):
            url, text = text, None  # a link shared as text
        if mimes:
            images = all(mime.startswith("image/") for mime in mimes)
            what = "photo" if images else "file"
        else:
            what = "url" if url else "note"
        if what == "note" and not text:
            raise InvalidError("empty capture")
        title = text.splitlines()[0][:200] if text else url
        return {
            "id": cid, "kind": what, "text": text, "url": url, "source": source,
            "created_at": created, "page_kind": kind, "fields": fields_for(kind, url),
            "title": title or when.strftime("%Y-%m-%d %H:%M"),
            "body": "\n\n".join(x for x in (url, text) if x),
        }  # fmt: skip

    def capture(
        self,
        c: dict[str, Any],
        blobs: list[tuple[str, str, int, str | None]],
        author: str,
    ) -> tuple[dict[str, str], bool]:
        """Save a prepared capture as a new page. Returns its reference and whether
        it is new. blobs are (sha256, mime, size, filename), already in files/.
        """
        cid, title, body, kind = c["id"], c["title"], c["body"], c["page_kind"]
        body = "\n\n".join(x for x in (body, *embeds(blobs, body)) if x)
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
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (page_id, self._slug(conn, title), title, body, kind or "note",
                 int(bool(kind)), json.dumps(c["fields"]), stamp, stamp),
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
            self.reindex(conn, page_id)
            conn.execute(ENQUEUE, {"capture": cid, "photo": None, "options": "{}",
                                   "now": stamp})  # fmt: skip
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
            conn.execute(
                "INSERT INTO page (id, slug, title, body, kind, kind_fixed, fields,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (page_id, p["slug"], p["title"], p["body"], p["kind"],
                 json.dumps(p["fields"]), p["created_at"], p["updated_at"]),
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
            raise NotFoundError(key)
        return row

    def recent(self, limit: int, kind: str | None = None) -> list[dict[str, Any]]:
        """Pages, newest change first; only those of one kind, if given."""
        if kind not in (None, *ALL_KINDS):
            raise InvalidError(f"kind must be one of {ALL_KINDS}")
        with self.connect() as conn:
            rows = _rows(
                conn,
                "SELECT id, slug, title, kind, kind_fixed, fields, created_at,"
                f" updated_at, {THUMB} AS thumb"
                " FROM page p WHERE deleted_at IS NULL"
                " AND coalesce(?, kind) = kind"
                " ORDER BY updated_at DESC, id DESC LIMIT ?",
                kind, limit,
            )  # fmt: skip
        return [{**r, "fields": json.loads(r["fields"])} for r in rows]

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
        return {**page, "fields": fields, "tags": tags, "captures": captures}

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
    ) -> dict[str, Any]:
        """Change a page's title and/or body, refusing an edit of a stale revision;
        and/or its kind (the user's choice, which ingest then keeps) and fields."""
        if kind not in (None, *KINDS):
            raise InvalidError(f"kind must be one of {KINDS}")
        with self.connect() as conn, transaction(conn):
            page = self._page_row(conn, key)
            if kind is not None or fields:
                self._set_kind(conn, page, kind, fields or {})
                if fields and "summary" in fields:  # indexed
                    self.reindex(conn, page["id"])
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
            new_body: str = page["body"] if body is None else lines(body)
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
                self.reindex(conn, page["id"])
            return self.page_in(conn, page["id"])

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
        if kind is not None and kind != page["kind"]:
            url = conn.execute(
                "SELECT url FROM capture WHERE page_id = ? AND url IS NOT NULL"
                " ORDER BY received_at LIMIT 1",
                (page["id"],),
            ).fetchone()
            fields = {**fields_for(kind, url and url[0]), **fields}  # the page's win
        for name, value in changes.items():
            if value is None:
                fields.pop(name, None)
            else:
                fields[name] = value
        if len(fields) > MAX_FIELDS:
            raise InvalidError(f"a page has at most {MAX_FIELDS} fields")
        conn.execute(
            "UPDATE page SET kind = ?, kind_fixed = ?, fields = ? WHERE id = ?",
            (kind or page["kind"], int(kind is not None or page["kind_fixed"]),
             json.dumps(fields), page["id"]),
        )  # fmt: skip

    def delete_page(self, key: str, undo: bool = False) -> None:
        """Move a page to the trash (or back); captures and files stay until a purge."""
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE page SET deleted_at = ? WHERE (id = ? OR slug = ?)"
                f" AND deleted_at IS {'NOT' if undo else ''} NULL",
                (None if undo else now(), key, key),
            )
        if cur.rowcount == 0:
            raise NotFoundError(key)

    def search(self, query: str, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        """Pages matching a query (see scrap.query): every word somewhere in the page
        (its title, tags, summary, body, or a photo's text or description; each
        word as a prefix), no NOT word anywhere, and all the filters. Ranked by bm25 of
        the page's best chunk, title, tag and summary matches weighing most; a query
        of filters alone lists its pages newest first. offset: skip that many hits
        (the next page of results)."""
        q = parse(query)
        if not q.terms and not q.filters:
            return []
        where, args = self._where(q)
        hits: dict[str, dict[str, Any]] = {}  # a page once, at its best chunk
        with self.connect() as conn:
            if q.positive:  # bm25() and snippet() refuse GROUP BY: group here instead
                # First the pages with every word in the title, then those with every
                # word in the title, tags or summary: bm25 alone lets a short body
                # that says a word twice beat a long page tagged with it
                every = " AND ".join(q.fts(t) for t in q.positive)
                tier = " c.id IN (SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ?)"
                rows = conn.execute(
                    "SELECT p.id, p.slug, p.title, p.kind, p.fields,"
                    " snippet(chunk_fts, 3, char(2), char(3), '…', 16) AS snippet"
                    " FROM chunk_fts JOIN chunk c ON c.id = chunk_fts.rowid"
                    " JOIN page p ON p.id = c.page_id"
                    f" WHERE chunk_fts MATCH ? AND {where}"
                    f" ORDER BY {tier} DESC, {tier} DESC, bm25(chunk_fts, {WEIGHTS})",
                    (" OR ".join(q.fts(t) for t in q.positive), *args,
                     f"title : ({every})", f"{{title tags summary}} : ({every})"),
                )  # fmt: skip
            else:
                rows = conn.execute(
                    "SELECT p.id, p.slug, p.title, p.kind, p.fields, p.body AS snippet"
                    f" FROM page p WHERE {where}"
                    " ORDER BY p.updated_at DESC, p.id DESC LIMIT ? OFFSET ?",
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
        pages have it (a: those with a or a/anything), in order."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT page_id, tag FROM tag JOIN page p ON p.id = tag.page_id"
                " WHERE p.deleted_at IS NULL"
            ).fetchall()
        return [[t, n] for t, n in sorted(tag_counts(rows).items())]

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
            elif f.key == "is" and f.value in ("personal", "work"):
                want = "IS 1" if f.value == "personal" else "IS NOT 1"
                sql.append(f"{no}(json_extract(p.fields, '$.personal') {want})")
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
