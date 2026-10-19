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

__all__ = ["Store", "NotFoundError", "ConflictError", "TooLargeError", "InvalidError"]

ULID = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")
SHA256 = re.compile(r"[0-9a-f]{64}")
BARE_URL = re.compile(r"https?://\S+")
WORD = re.compile(r"[^\W_]")  # a letter or digit
MAX_WORDS = 16  # search words used
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # all but \t and \n
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
HINT_FIELDS = {
    "todo": {"status": "open"},
    "consume": {"subtype": "read", "status": "open"},
}
SOURCES = ("pwa", "share", "mcp")
KINDS_SHOWN = ("ocr", "description", "excalidraw")
# One ingest job per distinct image of a photo capture (or the one photo asked for);
# job_one_active makes a repeat add nothing.
ENQUEUE = """
INSERT INTO job (kind, capture_id, source_sha256, options, run_after, created_at,
                 updated_at)
SELECT DISTINCT 'ingest', cb.capture_id, cb.sha256, :options, :now, :now, :now
FROM capture_blob cb
JOIN capture c ON c.id = cb.capture_id AND c.kind = 'photo'
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
    """Apply the missing migrations, one process at a time (flock on db.lock)."""
    with open(f"{db}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        version = schema_version(db)
        with closing(connect(db)) as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            for n, sql in enumerate(migrations()[version:], start=version + 1):
                try:
                    conn.executescript(
                        f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {n};\nCOMMIT;"
                    )
                except BaseException:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise


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
        source = _text(data, "source") or "pwa"
        created = _text(data, "created_at") or now()
        try:
            when = datetime.fromisoformat(created)
        except ValueError:
            raise InvalidError("created_at must be ISO 8601") from None
        if source not in SOURCES:
            raise InvalidError(f"source must be one of {SOURCES}")
        if hint not in (None, *HINT_FIELDS):
            raise InvalidError(f"hint must be one of {tuple(HINT_FIELDS)}")
        if not url and text and BARE_URL.fullmatch(text):
            url, text = text, None  # a link shared as text
        if mimes:
            images = all(mime.startswith("image/") for mime in mimes)
            kind = "photo" if images else "file"
        else:
            kind = "url" if url else "note"
        if kind == "note" and not text:
            raise InvalidError("empty capture")
        title = text.splitlines()[0][:200] if text else url
        fields = dict(HINT_FIELDS.get(hint or "", {}))
        if hint == "consume" and url:
            fields["source"] = url
        return {
            "id": cid, "kind": kind, "text": text, "url": url, "source": source,
            "created_at": created, "hint": hint, "fields": fields,
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
        cid, title, body, hint = c["id"], c["title"], c["body"], c["hint"]
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
                (page_id, self._slug(conn, title), title, body, hint or "note",
                 int(bool(hint)), json.dumps(c["fields"]), stamp, stamp),
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
            self._index(conn, page_id, title, body)
            conn.execute(ENQUEUE, {"capture": cid, "photo": None, "options": "{}",
                                   "now": stamp})  # fmt: skip
            return self._ref(conn, cid, page_id), True

    def _ref(self, conn: sqlite3.Connection, cid: str, page_id: str) -> dict[str, str]:
        slug = conn.execute("SELECT slug FROM page WHERE id = ?", (page_id,)).fetchone()
        return {"capture_id": cid, "page_id": page_id, "slug": slug[0]}

    def _slug(self, conn: sqlite3.Connection, title: str) -> str:
        ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore")
        base = re.sub(r"[^a-z0-9]+", "-", ascii_title.decode().lower())[:60].strip("-")
        base = base or "page"
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

    def _index(self, conn: sqlite3.Connection, page_id: str, title: str, body: str):
        # M1: one chunk per page, the title heading the body (a note's body
        # already starts with it). No control characters: snippets mark hits
        # with \x02 and \x03. Each becomes a space, so a lone \r or \v still
        # separates two words.
        text = body if body.startswith(title) else f"{title}\n\n{body}"
        text = CONTROL.sub(" ", text)
        conn.execute(  # derived text has chunks of its own
            "DELETE FROM chunk WHERE page_id = ? AND derived_id IS NULL", (page_id,)
        )
        conn.execute(
            "INSERT INTO chunk (page_id, ord, text) VALUES (?, 0, ?)", (page_id, text)
        )

    def reindex(self, conn: sqlite3.Connection, page_id: str) -> None:
        """Index a page's current title and body again."""
        row = conn.execute(
            "SELECT title, body FROM page WHERE id = ?", (page_id,)
        ).fetchone()
        self._index(conn, page_id, row[0], row[1])

    def _page_row(self, conn: sqlite3.Connection, key: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT *, (SELECT max(rev) FROM page_rev WHERE page_id = page.id) AS rev"
            " FROM page WHERE (id = ? OR slug = ?) AND deleted_at IS NULL",
            (key, key),
        ).fetchone()
        if row is None:
            raise NotFoundError(key)
        return row

    def recent(self, limit: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = _rows(  # thumb: the page's first image, if any
                conn,
                "SELECT id, slug, title, kind, fields, created_at, updated_at,"
                " (SELECT b.sha256 FROM capture c JOIN capture_blob cb"
                " ON cb.capture_id = c.id JOIN blob b USING (sha256)"
                " WHERE c.page_id = page.id AND b.mime LIKE 'image/%'"
                " ORDER BY c.received_at, cb.ord LIMIT 1) AS thumb"
                " FROM page WHERE deleted_at IS NULL"
                " ORDER BY updated_at DESC, id DESC LIMIT ?",
                limit,
            )
        return [{**r, "fields": json.loads(r["fields"])} for r in rows]

    def page(self, key: str) -> dict[str, Any]:
        """A page with its current revision and its captures and their blobs."""
        with self.connect() as conn:
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
                "SELECT tag FROM tag WHERE page_id = ? ORDER BY tag", (page["id"],)
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
        self, key: str, base_rev: int, title: str | None, body: str | None, author: str
    ) -> dict[str, Any]:
        """Change a page's title and/or body, refusing an edit of a stale revision."""
        with self.connect() as conn, transaction(conn):
            page = self._page_row(conn, key)
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
                    (page["id"], base_rev + 1, new_title, new_body, author, stamp),
                )
                self._index(conn, page["id"], new_title, new_body)
        return self.page(page["id"])

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

    def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Full-text search; each word must match somewhere in the page (its title
        and body, or a photo's text or description), the last one as a prefix."""
        query = CONTROL.sub(" ", query).replace('"', " ")
        # Words FTS can index (a letter or digit; "_" separates), each once, at
        # most MAX_WORDS: every word adds a subquery
        kept = [w for w in query.split() if WORD.search(w)]
        words = [f'"{w}"' for w in dict.fromkeys(kept)][:MAX_WORDS]
        if not words:
            return []
        words[-1] += "*"
        each = " AND p.id IN (SELECT c.page_id FROM chunk_fts JOIN chunk c ON"
        each += " c.id = chunk_fts.rowid WHERE chunk_fts MATCH ?)"
        hits: dict[str, dict[str, Any]] = {}  # a page once, at its best chunk
        with self.connect() as conn:
            # bm25() and snippet() refuse GROUP BY: group here instead
            for row in conn.execute(
                "SELECT p.id, p.slug, p.title, p.kind,"
                " snippet(chunk_fts, 0, char(2), char(3), '…', 16) AS snippet"
                " FROM chunk_fts JOIN chunk c ON c.id = chunk_fts.rowid"
                " JOIN page p ON p.id = c.page_id"
                " WHERE chunk_fts MATCH ? AND p.deleted_at IS NULL"
                + each * len(words)
                + " ORDER BY bm25(chunk_fts)",
                (" OR ".join(words), *words),
            ):
                hits.setdefault(row["id"], dict(row))
                if len(hits) == limit:
                    break
        for hit in hits.values():  # HTML-safe, with matches in <mark>
            snippet = html.escape(hit["snippet"])
            hit["snippet"] = snippet.replace("\x02", "<mark>").replace(
                "\x03", "</mark>"
            )
        return list(hits.values())

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
