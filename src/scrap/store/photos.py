"""Adding photos (and PDFs and text files, #234, #380) to a page that already exists
(#260)."""

import sqlite3
from typing import Any

from .constants import ENQUEUE, MCP, REV_INSERT, ULID
from .core import Core
from .db import transaction
from .errors import InvalidError
from .helpers import boxes_before, check_page, embeds, file_kind, now
from .roles import by_claude, takes_photos

Blob = tuple[str, str, int, str | None]  # sha256, mime, size, filename
MAX_ALT = 300  # characters of an embed's alt text


def alt_text(alt: str) -> str:
    """Alt text for an embed: one line, at most MAX_ALT characters, no brackets or
    backslashes, so it stays inside ![...].

    >>> alt_text(" A [right]\\n triangle ")
    'A (right) triangle'
    """
    alt = " ".join(alt.split())[:MAX_ALT]
    return alt.replace("[", "(").replace("]", ")").replace("\\", "/")


def addable(mime: str) -> bool:
    """Whether a file can be added to a page: an image, or a file ingest reads (a PDF,
    a text or Markdown file: FILE_TYPES)."""
    return mime.startswith("image/") or file_kind(mime) is not None


def placed_after(body: str, after: str, new: list[str]) -> str:
    """body with the embeds new put as paragraphs of their own after the line on which
    the text after ends (it must occur exactly once, as edit_page's old: else
    InvalidError), so a diagram goes under the question it belongs to.

    >>> placed_after("Q1 Find x.\\nWorking:\\n\\nQ2", "Find x", ["![](e)"])
    'Q1 Find x.\\n\\n![](e)\\n\\nWorking:\\n\\nQ2'
    """
    if not after.strip():
        raise InvalidError("after must not be empty")
    at, count, start = body.find(after), 0, 0
    while (found := body.find(after, start)) != -1 and count < 2:
        count, start = count + 1, found + 1  # overlapping ones count too
    if count != 1:
        why = "is not in the page's body" if count == 0 else "occurs more than once"
        raise InvalidError(f"after {why}: copy enough of the text to occur once")
    end = at + len(after)
    if not after.endswith("\n"):  # to the end of the line it ends on
        end = len(body) if (nl := body.find("\n", end)) == -1 else nl
    head, tail = body[:end].rstrip(), body[end:].lstrip("\n")
    return "\n\n".join(x for x in (head, *new, tail) if x)


def with_embeds(body: str, new: list[str], after: str | None = None) -> str:
    """body with the embeds new at its end, or after the line after ends on
    (placed_after)."""
    if new and after is not None:
        return placed_after(body, after, new)
    return "\n\n".join(x for x in (body.rstrip(), *new) if x)


def attach(
    conn: sqlite3.Connection,
    page_id: str,
    cid: str,
    blobs: list[Blob],
    author: str,
    source: str,
    created_at: str,
    stamp: str,
) -> None:
    """Record files (already in files/) on a page as a new capture cid, in conn's
    transaction: their blob rows, a photo capture if any is an image (so its images go
    to Claude, as Add photo's always have), else a file capture, its files in the order
    sent, and their ingest jobs (a PDF or text file is read for search, #234). The
    page's text is the caller's: gc, orphans and backup count the capture's files from
    capture_blob, and the page lists below its text those the text does not show."""
    images = any(mime.startswith("image/") for _, mime, *_ in blobs)
    conn.executemany(
        "INSERT INTO blob VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
        [(sha, mime, size, stamp) for sha, mime, size, _ in blobs],
    )
    conn.execute(  # received now: after the page's other captures
        "INSERT INTO capture VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, ?)",
        (cid, "photo" if images else "file", source, author, created_at, stamp,
         page_id),
    )  # fmt: skip
    conn.executemany(
        "INSERT INTO capture_blob VALUES (?, ?, ?, ?)",
        [(cid, i, sha, name) for i, (sha, _, _, name) in enumerate(blobs)],
    )
    conn.execute(ENQUEUE, {"capture": cid, "photo": None, "options": "{}",
                           "now": stamp})  # fmt: skip


class PhotosMixin(Core):
    def add_photos(
        self,
        key: str,
        cid: str,
        blobs: list[Blob],
        author: str,
        source: str = "pwa",
        created_at: str | None = None,
        *,
        after: str | None = None,
        alt: str = "",
        claude_only: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        """Add images and files: PDFs, text, Markdown (blobs: already in files/) to a
        page as a new capture cid: a photo capture if any is an image (so its images are
        read as Add photo's always were), else a file capture. Each new image's embed
        goes to the end of its text as it is now, as a text revision (appending loses
        nothing, so there is no revision to check); a file is not put in the text (the
        page lists it below), so files alone make no revision.
        They are queued for ingest as a capture's are: the images of a photo capture
        for Claude, a file to be read for search (#234). Returns the page, with
        appended_on (the revision the embeds went onto; None on a retry or with no
        image), and whether it is new: a retry with the same cid changes nothing.
        after: put the embeds after the line that text ends on (placed_after) instead
        of at the end; alt: their alt text. Source mcp (an MCP client's: add_svg, or
        the /mcp upload) makes the revision Claude's (source mcp: is:claude-edited);
        claude_only refuses a page not written over MCP (SCRAP_MCP_CONTENT_EDIT
        off)."""
        cid = cid.upper()
        if not ULID.fullmatch(cid):
            raise InvalidError("id must be a ULID")
        if not blobs or not all(addable(mime) for _, mime, *_ in blobs):
            raise InvalidError("only images, PDFs and text files can be added")
        images = any(mime.startswith("image/") for _, mime, *_ in blobs)
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
            if not takes_photos(conn, page["id"]):  # a topic (roles.takes_photos)
                raise InvalidError("Photos can't be added to a topic page")
            if claude_only and not by_claude(conn, page["id"]):
                raise InvalidError(
                    "only a page written over MCP: SCRAP_MCP_CONTENT_EDIT is off"
                )
            new = embeds(blobs, page["body"], alt_text(alt))
            body = with_embeds(page["body"], new, after)
            if new:
                body = check_page(body)  # before anything is written
            attach(
                conn, page["id"], cid, blobs, author, source, created_at or stamp, stamp
            )
            if new:  # a revision, as _put_text's, but no enrich: the photos' reading
                self._append_text(
                    conn, page, body, author, stamp, MCP if source == MCP else "web"
                )  # brings what follows
            added = self.page_in(conn, page["id"])
            return {**added, "appended_on": page["rev"] if images else None}, True

    def _append_text(
        self, conn: sqlite3.Connection, page: sqlite3.Row, body: str, author: str,
        stamp: str, rev_source: str = "web",
    ) -> None:  # fmt: skip
        """The page's text with the embeds added, as text revision rev + 1 (source
        web, or mcp for an MCP client's). Not a save: no enrich is queued (it would
        run before the photos are read; their reading brings the write-up and
        related calls)."""
        conn.execute(
            "UPDATE page SET body = ?, updated_at = ? WHERE id = ?",
            (body, stamp, page["id"]),
        )
        conn.execute(  # from the PWA, or an MCP client (add_svg, the /mcp upload)
            REV_INSERT,
            (page["id"], page["rev"] + 1, page["title"], body, author, rev_source,
             stamp),
        )  # fmt: skip
        self._body(conn, page["id"], boxes_before(page))
        self.reindex(conn, page["id"])
