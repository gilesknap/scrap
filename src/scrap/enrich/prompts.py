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
    FILES,
    IMAGES,
    MAX_BOARDS,
    MAX_BODY,
    MAX_FILES,
    MAX_IMAGES,
    MAX_VOCAB,
    RELATED_BODY,
    RELATED_FILES,
    RELATED_IMAGES,
    RELATED_SCHEMA,
    RELATED_WRITEUP,
    SAVE_REREAD,
    SCHEMA,
    WRITEUP_BODY,
    WRITEUP_IMAGES,
    WRITEUP_SCHEMA,
)

Image = dict[str, str | None]  # what photo ingest read from one: description, text
File = dict[str, str | None]  # what file ingest read from one: its name, its text


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


def page_files(conn: sqlite3.Connection, page_id: str) -> list[File]:
    """A page's readable files (a PDF, a text file) in order, each with its name and
    the text file ingest read from it (None if none yet)."""
    return [dict(r) for r in conn.execute(FILES, (page_id,))]


def read_files(files: Sequence[File]) -> list[tuple[int, str, str]]:
    """Each file something was read from: its number, its name and its text."""
    return [
        (n, f.get("name") or "", text)
        for n, f in enumerate(files, start=1)
        if (text := (f.get("text") or "").strip())
    ]


def file_text(files: Sequence[File]) -> str:
    """All the text read from a page's files, for how much there is to summarise."""
    return "\n".join(text for _, _, text in read_files(files))


def file_lines(files: Sequence[File], most: int) -> list[str]:
    """The user turn's lines for what was read from a page's files, each labelled
    with its number and name, cut to most characters in all; none if nothing was
    read."""
    items = []
    for n, name, text in read_files(files):
        name = one_line(name, 100)
        items.append(f"File {n}{f' ({name})' if name else ''}, its text:\n{text}")
    if not items:
        return []
    read = "\n".join(items)
    read = read if len(read) <= most else read[: most - 1] + "…"
    return ["Read from its files:", "<files>", quoted(read), "</files>"]


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
        about = quoted(one_line(p["summary"] or "", 150))
        title = quoted(one_line(unlink(p["title"]), 100))
        parts = [f"{n}. {title}", quoted(tags), about]
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
    page: sqlite3.Row,
    tags: list[str],
    summary: str,
    images: Sequence[Image] = (),
    writeup: str = "",
    files: Sequence[File] = (),
    files_most: int = RELATED_FILES,
) -> list[dict]:
    """The related call's user turn: the page in brief, with the start of what was
    read from its images and files (files_most characters: less unasked, ADR 38) and
    of its write-up, if it has one."""
    up = writeup.strip()
    up = up if len(up) <= RELATED_WRITEUP else up[: RELATED_WRITEUP - 1] + "…"
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
        *file_lines(files, files_most),
        *(["Start of Claude's write-up of it:", "<writeup>", quoted(up), "</writeup>"]
          if up else []),
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
    files: Sequence[File] = (),
    want_title: bool = False,
    files_most: int = MAX_FILES,
) -> list[dict[str, Any]]:
    """The user turn: the page (title, kind, tags, its text, what was read from its
    images and files) and for a link what was fetched. keep_text False puts a
    placeholder for the fetched text (as stored: a read keeps its link and summary
    only); what was read from its images and files is stored in full, as its own
    text is. want_title: a page made from a file, with no title of its own, asks for
    one (FILE_UNTITLED). files_most: the characters of its files' text sent (less
    unasked than on Ask, ADR 38)."""
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
        *file_lines(files, files_most),
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
    if want_title:
        parts.append("Write a title.")
    return [{"role": "user", "content": [{"type": "text", "text": "\n".join(parts)}]}]


def writeup_prompt(
    pages: list[dict[str, Any]], readout: bool = False
) -> tuple[str, str]:
    """The write-up call's fixed prompt, then the index of pages it may link to; the
    readout one (#453) for a page asked about that is not a board."""
    name = "writeup-readout" if readout else "writeup"
    text, version = claude.prompt(name, WRITEUP_SCHEMA)
    return f"{text}\n## Other pages\n\n{index_lines(pages) or '(none)'}\n", version


def writeup_message(
    page: sqlite3.Row,
    tags: list[str],
    boards: Sequence[dict[str, Any]],
    sent: Sequence[str | None],
    guidance: str | None,
    readout: bool = False,
) -> list[dict[str, Any]]:
    """The write-up call's user turn: each board image sent (sent: the JPEG's
    SHA-256 for the first MAX_BOARDS, None for one that could not be), numbered,
    then the page (kind, title, tags, its own text), what was read from its board
    images, and the owner's guidance, all quoted."""
    content: list[dict[str, Any]] = []
    for n, sha in enumerate(sent, start=1):
        if sha is None:
            continue
        content.append({"type": "text", "text": f"Image {n}:"})
        content.append({
            "type": "image",
            "source": {"type": "blob", "sha256": sha},
            "transformations": {"oversized_image": "error"},
        })  # fmt: skip
    attached = [n for n, sha in enumerate(sent, start=1) if sha is not None]
    images = [{"description": b["description"], "text": b["text"]} for b in boards]
    lines = [
        f"Kind: {page['kind']}",
        f"Title: {quoted(page['title'])}",
        f"Tags: {quoted(', '.join(tags)) or '(none)'}",
        "The page text (it may be another app's; the photo wins):",
        "<page>",
        quoted(plain(page["body"]).strip()[:WRITEUP_BODY]) or "(empty)",
        "</page>",
        *image_lines(images, WRITEUP_IMAGES),
    ]
    if readout:  # the readings are as of when each image was captured
        lines += [f"Image {n} was received {b['received_at']}."
                  for n, b in enumerate(boards, start=1)]  # fmt: skip
    if len(boards) > len(attached):
        shown = ", ".join(map(str, attached)) or "none"
        lines.append(
            f"Images attached: {shown} (at most {MAX_BOARDS}); of the others you"
            " have only what was read from them."
        )
    if guidance:
        lines += ["The owner's guidance for this write-up:", "<guidance>",
                  quoted(guidance), "</guidance>"]  # fmt: skip
    else:
        lines.append("The owner gave no guidance.")
    lines += ["", "Write the write-up."]
    content.append({"type": "text", "text": "\n".join(lines)})
    return [{"role": "user", "content": content}]
