"""Enrich: the prompts and the user turns sent to Claude."""

import hashlib
import sqlite3
from collections.abc import Sequence
from typing import Any

from .. import claude, fetch
from ..markdown import plain
from ..query import CONTROL
from ..store import unlink
from .constants import (
    DELIMITER,
    IMAGES,
    MAX_BODY,
    MAX_IMAGES,
    MAX_VOCAB,
    RELATED_BODY,
    RELATED_IMAGES,
    RELATED_SCHEMA,
    SAVE_REREAD,
    SCHEMA,
)

Image = dict[str, str | None]  # what photo ingest read from one: description, text


def quoted(text: str) -> str:
    """Data for a user turn with any delimiter tag in it (<page>, </images>...)
    neutralised, its < made &lt;: the model still reads it, but it cannot end the
    quote or open one. After any cut, so no part of a tag is left whole."""
    return DELIMITER.sub("&lt;", text)


def page_images(conn: sqlite3.Connection, page_id: str) -> list[Image]:
    """A page's images in order, each with its current description and text."""
    return [dict(r) for r in conn.execute(IMAGES, (page_id,))]


def image_lines(images: Sequence[Image], most: int) -> list[str]:
    """The user turn's lines for what was read from a page's images, each labelled
    with its number, cut to most characters in all; none if nothing was read."""
    items = []
    for n, image in enumerate(images, start=1):
        if about := (image.get("description") or "").strip():
            items.append(f"Image {n}, its description: {about}")
        if text := (image.get("text") or "").strip():
            items.append(f"Image {n}, its text:\n{text}")
    if not items:
        return []
    read = "\n".join(items)
    read = read if len(read) <= most else read[: most - 1] + "…"
    return ["Read from its images:", "<images>", quoted(read), "</images>"]


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


def related_message(
    page: sqlite3.Row, tags: list[str], summary: str, images: Sequence[Image] = ()
) -> list[dict]:
    """The related call's user turn: the page in brief, with the start of what was
    read from its images."""
    text = "\n".join([
        f"Kind: {page['kind']}",
        f"Title: {quoted(page['title'])}",
        f"Tags: {quoted(', '.join(tags)) or '(none)'}",
        f"Summary: {quoted(summary or '') or '(none)'}",
        "Start of its text:",
        "<page>",
        quoted(plain(page["body"]).strip()[:RELATED_BODY]) or "(empty)",
        "</page>",
        *image_lines(images, RELATED_IMAGES),
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
    images: Sequence[Image] = (),
) -> list[dict[str, Any]]:
    """The user turn: the page (title, kind, tags, its text, what was read from its
    images) and for a link what was fetched. keep_text False puts a placeholder for
    the fetched text (as stored: a read keeps its link and summary only)."""
    body = quoted(plain(page["body"]).strip()[:MAX_BODY])
    parts = [
        f"Kind: {page['kind']}",
        f"Its tags: {quoted(', '.join(tags)) or '(none)'}",
        f"Title: {quoted(page['title'])}",
        "Text:",
        "<page>",
        body or "(empty)",
        "</page>",
        *image_lines(images, MAX_IMAGES),
    ]
    if link:
        parts += ["", f"This page is a saved link: {quoted(link)}"]
        if got is not None:
            text = quoted(got.text)
            if not keep_text:  # the digest of the text as fetched
                digest = hashlib.sha256(got.text.encode()).hexdigest()[:16]
                text = f"[fetched text: {len(got.text)} characters, sha256 {digest}]"
            parts += [
                f"Fetched from: {quoted(got.url)}",
                f"Its title: {quoted(got.title) or '(none)'}",
                f"Its description: {quoted(got.description) or '(none)'}",
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
                parts.append(f"It could not be fetched: {quoted(failed or '')}")
    parts += ["", "Write a summary." if want_summary else "No summary is wanted."]
    return [{"role": "user", "content": [{"type": "text", "text": "\n".join(parts)}]}]
