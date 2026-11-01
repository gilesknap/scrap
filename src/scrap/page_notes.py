"""What a single page's download adds to its Markdown (and the export does not):
tags, status and topics in the front matter, Claude's notes under one marked heading,
the pages that link here, the text read from a PDF or text file, and `[[slug]]` links
as full addresses when $SCRAP_PUBLIC_URL is set. A page link with no label of its own
shows its page's title (#508), as in the app: `[Title](address)`, or `[[slug|Title]]`
with no address to make.

Claude's notes are kept out of an exported page's file (export.py puts them in
_claude/<slug>.md, with _notes): an import would read everything after the front matter
as the owner's text, so model text there would come back as theirs (ADR 0020, 0027). A
download is a copy to read or share, not a backup format.
"""

import sqlite3
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from .markdown import rewrite, wiki_link, wiki_titled
from .public import public_urls
from .store import Store

__all__ = ["NOTES_HEADING", "Extras", "gather", "page_titles"]

NOTES_HEADING = "## Claude's notes (written by a model, may be wrong)"
MAX_FILE_TEXT = 20_000  # characters of a PDF's or text file's text a download holds


@dataclass
class Extras:
    """What page_markdown adds for a single page's download."""

    front: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # lines from the heading, or none
    linked_from: list[str] = field(default_factory=list)
    address: str | None = None  # the first $SCRAP_PUBLIC_URL, if set
    titles: dict[str, str] = field(default_factory=dict)  # of the pages linked to

    def links(self, text: str) -> str:
        """text with its [[slug]] links as full addresses, if there is an address to
        make them with, else as they are; either way one with no label shows its
        page's title, if titles has it."""
        if not self.address:
            if not self.titles:
                return text
            return rewrite(text, lambda link: wiki_titled(link, self.titles))
        base = self.address

        def href(slug: str) -> str:
            return f"{base}/p/{quote(slug, safe='')}"

        return rewrite(text, lambda link: wiki_link(link, href, self.titles))


def page_titles(p: dict[str, Any]) -> dict[str, str]:
    """The titles of the pages a page (as store.page has it) and Claude's notes about
    it link to: its text's, its write-up's and its related pages'."""
    up = (p.get("writeup") or {}).get("current") or {}
    related = {r["slug"]: r["title"] for r in p.get("related", [])}
    return {**related, **up.get("titles", {}), **p.get("titles", {})}


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
    """A list of links to pages, each showing its title (Extras.links, page_titles)."""
    return [f"- [[{r['slug']}]]" for r in rows]


def gather(
    store: Store, conn: sqlite3.Connection, page_id: str, notes: bool = True
) -> Extras:
    """The extras for one page: notes=False leaves out Claude's notes only."""
    p = store.page_in(conn, page_id)
    backlinks = store.backlinks(p["slug"])
    titles = {r["slug"]: r["title"] for r in backlinks} | page_titles(p)
    extras = Extras(address=(public_urls() or [None])[0], titles=titles)
    if p["fields"].get("status"):
        extras.front["status"] = p["fields"]["status"]
    if p["tags"]:
        extras.front["tags"] = p["tags"]
    if p["topics"]:
        extras.front["topics"] = [t["slug"] for t in p["topics"]]
    linked = _pages(backlinks)
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
