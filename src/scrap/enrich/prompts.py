"""Enrich: the prompts and the user turns sent to Claude."""

import hashlib
import sqlite3
from typing import Any

from .. import claude, fetch
from ..markdown import plain
from ..query import CONTROL
from ..store import unlink
from .constants import MAX_BODY, MAX_VOCAB, RELATED_SCHEMA, SAVE_REREAD, SCHEMA


def vocabulary(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """The tags in use (on pages not in the trash), most used first."""
    return [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT t.tag, count(*) FROM tag t JOIN page p ON p.id = t.page_id"
            " WHERE p.deleted_at IS NULL GROUP BY t.tag"
            " ORDER BY count(*) DESC, t.tag LIMIT ?",
            (MAX_VOCAB,),
        )
    ]


def one_line(text: str, most: int) -> str:
    text = " ".join(CONTROL.sub(" ", text).split())
    return text if len(text) <= most else text[: most - 1] + "…"


def index_lines(pages: list[dict[str, Any]]) -> str:
    """The compact index: one line a page, about 40 tokens."""
    lines = []
    for n, p in enumerate(pages, start=1):
        tags = " ".join(f"#{t}" for t in p["tags"][:6])
        about = one_line(p["summary"] or "", 150)
        parts = [f"{n}. {one_line(unlink(p['title']), 100)}", tags, about]
        lines.append(" | ".join(x for x in parts if x))
    return "\n".join(lines)


def system_prompt(conn: sqlite3.Connection) -> tuple[str, str]:
    """The fixed prompt, then the tags in use; and the prompt's version (of the fixed
    part and the schema)."""
    text, version = claude.prompt("enrich", SCHEMA)
    vocab = ", ".join(f"{t} ({n})" for t, n in vocabulary(conn)) or "(none yet)"
    return f"{text}\n## Tags in use\n\n{vocab}\n", version


def related_prompt(pages: list[dict[str, Any]]) -> tuple[str, str]:
    """The related call's fixed prompt, then the index of candidate pages."""
    text, version = claude.prompt("related", RELATED_SCHEMA)
    return f"{text}\n## Other pages\n\n{index_lines(pages) or '(none)'}\n", version


def related_message(page: sqlite3.Row, tags: list[str], summary: str) -> list[dict]:
    """The related call's user turn: the page in brief."""
    text = "\n".join([
        f"Kind: {page['kind']}",
        f"Title: {page['title']}",
        f"Tags: {', '.join(tags) or '(none)'}",
        f"Summary: {summary or '(none)'}",
        "Start of its text:",
        "<page>",
        plain(page["body"]).strip()[:2000] or "(empty)",
        "</page>",
    ])  # fmt: skip
    return [{"role": "user", "content": [{"type": "text", "text": text}]}]


def page_message(
    page: sqlite3.Row,
    tags: list[str],
    link: str | None,
    got: fetch.Fetched | None,
    failed: str | None,
    want_summary: bool,
    keep_text: bool = True,
) -> list[dict[str, Any]]:
    """The user turn: the page (title, kind, tags, its text) and for a link what was
    fetched. keep_text False puts a placeholder for the fetched text (as stored: a read
    keeps its link and summary only)."""
    body = plain(page["body"]).strip()[:MAX_BODY]
    parts = [
        f"Kind: {page['kind']}",
        f"Its tags: {', '.join(tags) or '(none)'}",
        f"Title: {page['title']}",
        "Text:",
        "<page>",
        body or "(empty)",
        "</page>",
    ]
    if link:
        parts += ["", f"This page is a saved link: {link}"]
        if got is not None:
            text = got.text
            if not keep_text:
                digest = hashlib.sha256(text.encode()).hexdigest()[:16]
                text = f"[fetched text: {len(text)} characters, sha256 {digest}]"
            parts += [
                f"Fetched from: {got.url}",
                f"Its title: {got.title or '(none)'}",
                f"Its description: {got.description or '(none)'}",
                "<fetched>",
                text or "(no readable text)",
                "</fetched>",
            ]
        else:
            if failed == SAVE_REREAD:
                parts.append(
                    "The link was not fetched again; summarise from the page text"
                    " and address."
                )
            else:
                parts.append(f"It could not be fetched: {failed}")
    parts += ["", "Write a summary." if want_summary else "No summary is wanted."]
    return [{"role": "user", "content": [{"type": "text", "text": "\n".join(parts)}]}]
