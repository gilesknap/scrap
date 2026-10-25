"""Adding photos to a page that already exists (#260)."""

from typing import Any

from .constants import ENQUEUE, ULID
from .core import Core
from .db import transaction
from .errors import InvalidError
from .helpers import check_page, embeds, now

Blob = tuple[str, str, int, str | None]  # sha256, mime, size, filename


class PhotosMixin(Core):
    def add_photos(
        self,
        key: str,
        cid: str,
        blobs: list[Blob],
        author: str,
        source: str = "pwa",
        created_at: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Add images (blobs: already in files/) to a page as a new photo capture cid,
        and each new one's embed to the end of its text as it is now, as a text
        revision (appending loses nothing, so there is no revision to check); they
        are queued for ingest, as a capture's photos are. Returns the page, with
        appended_on (the revision the embeds went onto; None on a retry), and whether
        it is new: a retry with the same cid changes nothing."""
        cid = cid.upper()
        if not ULID.fullmatch(cid):
            raise InvalidError("id must be a ULID")
        if not blobs or not all(mime.startswith("image/") for _, mime, *_ in blobs):
            raise InvalidError("only images can be added to a page")
        stamp = now()
        with self.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT page_id FROM capture WHERE id = ?", (cid,)
            ).fetchone()
            if row:
                page = self.page_in(conn, row[0])
                if key not in (page["id"], page["slug"]):
                    raise InvalidError("id is already another page's capture")
                return {**page, "appended_on": None}, False
            page = self._page_row(conn, key)
            new = embeds(blobs, page["body"])
            body = "\n\n".join(x for x in (page["body"].rstrip(), *new) if x)
            if new:
                body = check_page(body)  # before anything is written
            conn.executemany(
                "INSERT INTO blob VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                [(sha, mime, size, stamp) for sha, mime, size, _ in blobs],
            )
            conn.execute(  # received now: after the page's other captures
                "INSERT INTO capture VALUES (?, 'photo', NULL, NULL, ?, ?, ?, ?, ?)",
                (cid, source, author, created_at or stamp, stamp, page["id"]),
            )
            conn.executemany(
                "INSERT INTO capture_blob VALUES (?, ?, ?, ?)",
                [(cid, i, sha, name) for i, (sha, _, _, name) in enumerate(blobs)],
            )
            if new:
                self._put_text(conn, page, page["title"], body, author, False)
            conn.execute(ENQUEUE, {"capture": cid, "photo": None, "options": "{}",
                                   "now": stamp})  # fmt: skip
            added = self.page_in(conn, page["id"])
            return {**added, "appended_on": page["rev"]}, True
