"""What a single page's download adds to its Markdown (and the export does not):
tags, status and topics in the front matter, Claude's notes under one marked heading,
the pages that link here, the text read from a PDF or text file, and `[[slug]]` links
as full addresses when $SCRAP_PUBLIC_URL is set.

Claude's notes are kept out of an exported page's file (export.py puts them in
_claude/<slug>.md, with _notes): an import would read everything after the front matter
as the owner's text, so model text there would come back as theirs (ADR 0020, 0027). A
download is a copy to read or share, not a backup format.
"""

import sqlite3
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from .markdown import Link, rewrite
from .public import public_urls
from .store import Store

__all__ = ["NOTES_HEADING", "Extras", "gather"]

NOTES_HEADING = "## Claude's notes (written by a model, may be wrong)"
MAX_FILE_TEXT = 20_000  # characters of a PDF's or text file's text a download holds


@dataclass
class Extras:
    """What page_markdown adds for a single page's download."""

    front: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # lines from the heading, or none
    linked_from: list[str] = field(default_factory=list)
    address: str | None = None  # the first $SCRAP_PUBLIC_URL, if set

    def links(self, text: str) -> str:
        """text with its [[slug]] links as full addresses, if there is an address to
        make them with; else as they are."""
        if not self.address:
            return text
        base = self.address

        def full(link: Link) -> str | None:
            if link.kind != "wiki" or link.embed:
                return None
            label = (link.label or link.target).replace("[", "(").replace("]", ")")
            return f"[{label}]({base}/p/{quote(link.target, safe='')})"

        return rewrite(text, full)


def file_text(conn: sqlite3.Connection, cid: str, sha: str) -> tuple[str, bool] | None:
    """A PDF's or text file's text as scrap read it, at most MAX_FILE_TEXT characters,
    and whether it was cut; None if it has none."""
    row = conn.execute(
        "SELECT substr(text, 1, ?), length(text) > ? FROM derived"
        " WHERE capture_id = ? AND source_sha256 = ? AND kind = 'ocr'"
        " AND superseded_at IS NULL AND text <> ''",
        (MAX_FILE_TEXT, MAX_FILE_TEXT, cid, sha),
    ).fetchone()
    return (row[0], bool(row[1])) if row and row[0] else None


def _quoted(text: str) -> list[str]:
    """Model text as a block quote, so a heading or rule in it cannot end the section
    or pose as one of the download's own."""
    return [f"> {line}".rstrip() for line in text.splitlines()]


def _pages(rows: list[dict[str, Any]]) -> list[str]:
    return [f"- [[{r['slug']}]] {r['title']}".rstrip() for r in rows]


def gather(
    store: Store, conn: sqlite3.Connection, page_id: str, notes: bool = True
) -> Extras:
    """The extras for one page: notes=False leaves out Claude's notes only."""
    p = store.page_in(conn, page_id)
    extras = Extras(address=(public_urls() or [None])[0])
    if p["fields"].get("status"):
        extras.front["status"] = p["fields"]["status"]
    if p["tags"]:
        extras.front["tags"] = p["tags"]
    if p["topics"]:
        extras.front["topics"] = [t["slug"] for t in p["topics"]]
    linked = _pages(store.backlinks(p["slug"]))
    extras.linked_from = extras.links("\n".join(linked)).split("\n") if linked else []
    if notes:
        extras.notes = _notes(p, extras)
    return extras


def _notes(p: dict[str, Any], extras: Extras) -> list[str]:
    up = (p.get("writeup") or {}).get("current")
    enriched = p.get("enrich") or {}
    summary = (up and up["summary"]) or enriched.get("summary")
    parts: list[list[str]] = []
    if summary:
        parts.append(["**Summary**", "", *_quoted(summary)])
    if p["model_tags"]:
        parts.append([f"**Tags Claude added:** {', '.join(p['model_tags'])}"])
    if up and up["text"]:
        what = "Topic synthesis" if p.get("topic") else "Write-up"
        parts.append([f"**{what}**", "", *_quoted(up["text"])])
    related = [r for r in p["related"] if r["via"] != "link"]  # links: Linked from
    if related:
        parts.append(["**Related pages**", "", *_pages(related)])
    if not parts:
        return []
    lines = [NOTES_HEADING]
    for part in parts:
        lines += ["", *part]
    return extras.links("\n".join(lines)).split("\n")
