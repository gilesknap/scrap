"""The Store base: paths, connections, blobs, slugs."""

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from .constants import SHA256
from .db import connect, migrate
from .errors import NoSuchPage, NotFoundError
from .helpers import revision_window, slug_base
from .indexing import index_page
from .todo import cols as todo_cols


class Core:
    if TYPE_CHECKING:
        # The methods the mixins call on one another live on the assembled Store.
        def __getattr__(self, name: str) -> Any: ...

    def __init__(self, data_dir: Path | str):
        self.dir = Path(data_dir)
        self.db = self.dir / "scrap.db"
        self.files = self.dir / "files"
        self.window = revision_window()  # seconds: see _record_meta
        # The current prompt versions (writeup), set by whoever makes the Store
        # (app.create_app: enrich.prompt_versions()); is:outdated compares a write-up's
        # with writeup (missing: not checked)
        self.prompts: dict[str, str] = {}

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

    def _page_row(
        self, conn: sqlite3.Connection, key: str, trashed: bool = False
    ) -> sqlite3.Row:
        """A page by id or slug; one in the trash is NoSuchPage unless trashed."""
        row = conn.execute(
            f"SELECT *, {todo_cols('page')},"
            " (SELECT max(rev) FROM page_rev WHERE page_id = page.id) AS rev"
            " FROM page WHERE (id = ? OR slug = ?) AND (deleted_at IS NULL OR ?)",
            (key, key, trashed),
        ).fetchone()
        if row is None:
            raise NoSuchPage(key)
        return row

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
