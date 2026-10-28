"""Pure helpers: validation, tag and field handling, row shaping."""

import json
import math
import mimetypes
import os
import re
import secrets
import sqlite3
import time
import unicodedata
from datetime import UTC, datetime
from typing import Any

from ..query import (
    CONTROL,
    MAX_FILTERS,
    MAX_TERMS,
    PRIORITIES,
    Query,
    day,
    parse,
)
from .constants import (
    BLOB_ADDRESS,
    CROCKFORD,
    DEFAULT_FIELDS,
    FILE_TYPES,
    MAX_INT,
    MAX_PAGE,
    MAX_TAG,
    MAX_TAGS,
    MD_LINK,
    PRIORITY_NAMES,
    SURROGATE,
    TODO,
    UPLOAD_TOKEN,
    WIKI_LINK,
    BlobRef,
    Value,
)
from .errors import InvalidError
from .types import Meta


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


def revision_window() -> float:
    """Seconds within which one author's changes to a page's kind and tags fold into
    one revision, from SCRAP_REVISION_WINDOW (default 300; 0: every change is one)."""
    value = os.environ.get("SCRAP_REVISION_WINDOW", "300")
    try:
        window = float(value)
    except ValueError:
        window = -1.0
    if not window >= 0:  # also NaN
        raise SystemExit(
            f"SCRAP_REVISION_WINDOW must be a number of seconds, not {value!r}"
        )
    return window


def seconds_between(earlier: str, later: str) -> float:
    """The seconds from one of now()'s timestamps to another."""
    start, end = datetime.fromisoformat(earlier), datetime.fromisoformat(later)
    return (end - start).total_seconds()


def too_big(size: int, most: int = MAX_PAGE) -> str:
    """Why a page of size bytes is refused: in bytes, so the boundary is clear."""
    mb = " (1 MB)" if most == MAX_PAGE else ""
    return f"the page text is {size:,} bytes, and a page holds at most {most:,}{mb}"


def check_page(body: str, was: str | None = None) -> str:
    """body, if it is within MAX_PAGE bytes of UTF-8 or is unchanged from was (a page
    imported over the limit can still be retitled); else InvalidError, saying so."""
    size = len(body.encode())
    if size > MAX_PAGE and body != was:
        raise InvalidError(too_big(size))
    return body


def unlink(text: str) -> str:
    """Markdown text with each link or image reduced to its label, and a page link to
    its label (else slug): addresses are not words to search for. Not handled:
    reference definitions ([r]: url), link text holding brackets, a URL with
    parentheses (leaves a ")"), and code (unlinked too)."""
    text = WIKI_LINK.sub(lambda m: m[2] or m[1], text)
    return MD_LINK.sub(r"\1", text)


def body_refs(text: str) -> set[str]:
    """The stored files a page's text refers to, by SHA-256: any mention of a file's
    address counts (an image, a link, even in code), so a page never loses a file it
    shows. The one place page text is read for references (scrap gc, the save warning's
    counts). Deliberately not the Markdown parser (markdown.py): gc deletes what this
    misses, so it errs on keeping a file (in code, an absolute URL, broken Markdown)."""
    return set(BLOB_ADDRESS.findall(text))


# A .md file sent untyped is typed by its name (uploads.mimes, the importer): Python's
# own table has no .md before 3.13, and a slim image has no /etc/mime.types to add it
mimetypes.add_type("text/markdown", ".md")


def file_kind(mime: str) -> str | None:
    """pdf or text for a file ingest reads locally (FILE_TYPES, as IS_FILE tests it in
    SQL), else None."""
    base = mime.split(";", 1)[0].strip().lower()
    if base not in FILE_TYPES:
        return None
    return "pdf" if base == "application/pdf" else "text"


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


def placed(text: str, blobs: list[BlobRef]) -> str:
    """text with each token for one of blobs (UPLOAD_TOKEN, blobs in the order they
    were sent) replaced by that file's embed: an image's
    ![](/api/blobs/<sha>/preview?size=2048), another file's [name](/api/blobs/<sha>)
    link. A token for no upload stays as typed.

    >>> blobs = [("a" * 64, "image/jpeg", 1, "x.jpg"),
    ...          ("b" * 64, "application/pdf", 1, "a [1].pdf")]
    >>> placed("⟦image 1⟧, ⟦file 2: a.pdf⟧ ⟦image 3⟧", blobs)  # doctest: +ELLIPSIS
    '![](/api/blobs/aaa...a/preview?size=2048), [a 1.pdf](/api/...b) ⟦image 3⟧'
    """

    def embed(m: re.Match[str]) -> str:
        n = int(m[1])
        if n > len(blobs):
            return m[0]
        sha, mime, _, name = blobs[n - 1]
        if mime.startswith("image/"):
            return f"![](/api/blobs/{sha}/preview?size=2048)"
        name = re.sub(r"[\[\]\\]", "", name or "")  # no bracket, nor one escaped
        label = " ".join(CONTROL.sub(" ", name).split())
        link = f"[{label or 'file'}](/api/blobs/{sha})"
        # after a "!" (Look!⟦file 1⟧) the link would read as an image: a space between
        return f" {link}" if m.start() and text[m.start() - 1] == "!" else link

    return UPLOAD_TOKEN.sub(embed, text)


def untokened(text: str, uploads: int) -> str:
    """text without its tokens for its uploads (UPLOAD_TOKEN, the first uploads of
    them): the words a capture has of its own, for its title."""
    return UPLOAD_TOKEN.sub(lambda m: "" if int(m[1]) <= uploads else m[0], text)


def checked_query(query: str) -> Query:
    """parse(query), refused if it has more words or filters than a search takes: one
    left out could be a NOT word or -tag:, and the results would be broader than
    asked."""
    q = parse(query)
    if q.dropped:
        raise InvalidError(
            f"too many search terms: at most {MAX_TERMS} distinct words and"
            f" {MAX_FILTERS} filters ({q.dropped} too many); nothing was searched"
        )
    return q


def tag_path(tag: str) -> str:
    """A tag without empty path segments: /lead, trail/ and a//b become lead, trail and
    a/b (#87), so no blank tag or parent reaches the tag tree, and tag:/ finds none."""
    return "/".join(part for part in tag.split("/") if part.strip())


def clean_tags(tags: list[str], most: int = MAX_TAGS) -> list[str]:
    """Tags as imported ones are: one space between words, no leading #, lower case;
    each 1 to 64 characters, at most most of them, each once, in order."""
    if len(tags) > most:
        raise InvalidError(f"at most {most} tags")
    out: list[str] = []
    for tag in tags:
        try:
            tag.encode()
        except UnicodeEncodeError:
            raise InvalidError("a tag must be valid Unicode") from None
        new = " ".join(CONTROL.sub(" ", tag).split()).lstrip("#").lower().strip()
        new = tag_path(unicodedata.normalize("NFC", new))
        if not new or len(new) > MAX_TAG:
            raise InvalidError(f"a tag must be 1 to {MAX_TAG} characters: {tag[:80]!r}")
        if new not in out:
            out.append(new)
    return out


def check_todo(name: str, value: Any) -> str | None:
    """A due date (YYYY-MM-DD) or a priority (high, medium, low) as given, checked;
    None clears it."""
    if value is None:
        return None
    if name == "due":
        if not isinstance(value, str) or day(value) is None:
            raise InvalidError(f"{name} must be a date, YYYY-MM-DD")
        return value
    if value not in PRIORITIES:
        raise InvalidError(f"priority must be one of {PRIORITIES}")
    return value


def todo_columns(
    kind: str, fields: dict[str, Any]
) -> tuple[dict[str, str | None], dict[str, Any]]:
    """A todo's due and priority, out of fields it was imported with (Thoth's due_date
    and priority: kept in fields if not a date or a priority), and the other fields."""
    out: dict[str, str | None] = dict.fromkeys(TODO)
    if kind != "todo":
        return out, fields
    rest = dict(fields)
    if isinstance(when := rest.get("due"), str) and day(when):
        out["due"] = rest.pop("due")
    rank = rest.get("priority")
    rank = PRIORITY_NAMES.get(rank, rank) if isinstance(rank, str) else None
    if rank in PRIORITIES:
        out["priority"] = rank
        rest.pop("priority")
    return out, rest


def todo_only(page: dict[str, Any]) -> dict[str, Any]:
    """A page (or a list's row) with its due and priority if it is a todo, else None;
    and its task boxes as tasks: {done, total} (any kind's)."""
    if page.get("kind") != "todo":
        page.update(dict.fromkeys(TODO))
    if "task_total" in page:
        page["tasks"] = {"done": page.pop("task_done"), "total": page.pop("task_total")}
    return page


def slug_base(title: str) -> str:
    """A slug made from a title, before any suffix that makes it unique."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore")
    base = re.sub(r"[^a-z0-9]+", "-", ascii_title.decode().lower())[:60].strip("-")
    return base or "page"


def _text(data: dict[str, Any], key: str, indent: bool = False) -> str | None:
    """A string field, tidied: None if blank.

    indent keeps the first line's own indent (only blank lines before it go): four
    spaces make it code, and `    # x` is no heading.
    """
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise InvalidError(f"{key} must be a string")
    if not value:
        return None
    if SURROGATE.search(value):
        raise InvalidError(f"{key} must be valid Unicode (a lone surrogate)")
    value = lines(value)
    if indent:
        value = re.sub(r"\A(?:[ \t]*\n)+", "", value).rstrip()
    else:
        value = value.strip()
    return value or None


def lines(text: str) -> str:
    """Unix line ends: multipart form fields arrive with CRLF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def check_value(name: str, value: Any) -> None:
    """Refuse a field value the PWA could not show as stored: a float that is not
    finite (NaN, Infinity, or 1e400, which parses to it) or an int past +-2**53."""
    if isinstance(value, bool):
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidError(f"field {name}: a number must be finite")
    if isinstance(value, int) and abs(value) > MAX_INT:
        raise InvalidError(f"field {name}: a whole number is at most +-2**53")


def fields_for(kind: str | None, url: str | None) -> dict[str, Value]:
    """A kind's default fields; consume also links its source, if it has one."""
    fields: dict[str, Value] = dict(DEFAULT_FIELDS.get(kind or "", {}))
    if kind == "consume" and url:
        fields["source"] = url
    return fields


def meta_of(row: sqlite3.Row, when: str) -> Meta:
    """A page_meta_rev row's state before or after (when) its change."""
    return Meta(
        row[f"kind_{when}"], row[f"fixed_{when}"], json.loads(row[f"tags_{when}"])
    )


def meta_row(row: sqlite3.Row) -> dict[str, Any]:
    """A page_meta_rev row as data: its tags as lists, and those added and removed."""
    before, after = json.loads(row["tags_before"]), json.loads(row["tags_after"])
    return {
        **dict(row), "tags_before": before, "tags_after": after,
        "fixed_before": bool(row["fixed_before"]),
        "fixed_after": bool(row["fixed_after"]),
        "fields_added": json.loads(row["fields_added"]),
        "fields_was": json.loads(row["fields_was"]),
        "tags_added": [t for t in after if t not in before],
        "tags_removed": [t for t in before if t not in after],
    }  # fmt: skip


def boxes_before(page: sqlite3.Row) -> tuple[int, int]:
    """A page's task boxes (ticked, all) before an edit, as its status follows them: a
    todo's counts; none for a page that was not a todo, so one filed as a todo by this
    edit (by its boxes, or by hand) is filed as a new capture of its text would be: done
    if every box is ticked."""
    return (page["task_done"], page["task_total"]) if page["kind"] == "todo" else (0, 0)


def tag_counts(rows: list[Any]) -> dict[str, int]:
    """How many pages have each tag, from (page id, tag) rows: a/b counts for a too."""
    pages: dict[str, set[str]] = {}
    for page_id, tag in rows:
        parts = tag.split("/")
        for n in range(1, len(parts) + 1):
            pages.setdefault("/".join(parts[:n]), set()).add(page_id)
    return {tag: len(ps) for tag, ps in pages.items()}
