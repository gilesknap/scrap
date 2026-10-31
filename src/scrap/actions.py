"""A list of actions becomes task boxes: the one checker and writer (#191, #193).

Photo ingest and text enrich both ask Claude (prompts/items.md) whether the whole page
is a to-do list, and for its entries. When it says so with high confidence, and the page
is an unfixed note (or a whiteboard that ingest, not the user, chose) with no task boxes
yet, the entries are appended below the user's text as `- [ ] item` lines in one text
revision by Claude (ADR 0022), which revert (to_rev) undoes. The existing task-box rule
then files the page as a todo. The user's words are never rewritten, a fixed kind
and a page with boxes are never touched, and a page edited since Claude read it is
left alone.
Entries come from untrusted text and images: they are cut down to plain one-line text.
"""

import html
import logging
import re
import sqlite3
from datetime import date
from typing import Any

from .markdown import tasks
from .query import CONTROL
from .store import CLAUDE, MCP, ConflictError, InvalidError, Store
from .store.roles import may_rekind

__all__ = [
    "MAX_ITEMS",
    "MAX_ITEM",
    "MEDIUM_ITEMS",
    "accepted",
    "append",
    "clean_due",
    "clean_items",
    "clean_intent",
    "due_day",
    "set_due",
]

log = logging.getLogger(__name__)

MAX_ITEMS = 30  # boxes added to a page at most
MAX_ITEM = 200  # characters in one
INTENT, HIGH = "list-of-actions", "high"
MEDIUM_ITEMS = 3  # entries that let a photo of handwriting pass at medium confidence
DUE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}-\d{2}")  # YYYY-MM-DD, or MM-DD (no year)
LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")  # [label](address): label only
# List, quote and heading marks, numbers, checkbox marks and strike-through, leading
LEAD = re.compile(r"^(?:[-+*#>|=]+|\d{1,3}[.)]|\[[ xX]?\]|~~|\s)+")
# Markup that would make more of an entry than text: brackets, code, tags
MARKUP = re.compile(r"[\[\]`<>]|~~|(?<!\w)\*+|\*+(?!\w)")
ESCAPE = re.compile(r"\\(?=[!-/:-@\[-`{-~])")  # a backslash that escapes punctuation
# What would autolink or decode: a scheme and "://", "www.", and character references
SCHEME = re.compile(r"\b[a-z][a-z0-9+.-]*://|\bwww\.|\bmailto:", re.IGNORECASE)
EDGE = re.compile(r"(?<!\w)_+|_+(?!\w)")  # emphasis underscores at word edges


def clean_intent(raw: dict[str, Any]) -> tuple[str, str]:
    """Claude's intent and confidence, each one of the schema's values (else the
    harmless other / low)."""
    intent, confidence = raw.get("intent"), raw.get("confidence")
    return (
        intent if intent in ("list-of-actions", "reference") else "other",
        confidence if confidence in ("high", "medium") else "low",
    )


def clean_items(raw: Any) -> list[tuple[str, bool]]:
    """Claude's entries as (text, done): plain one-line text of at most MAX_ITEM
    characters (no control characters, line breaks, leading list or heading marks,
    links, code or tags), without empty ones or repeats, at most MAX_ITEMS."""
    out: list[tuple[str, bool]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
            continue
        text = LINK.sub(r"\1", CONTROL.sub(" ", entry["text"]))
        text = " ".join(text.replace(" ", " ").replace(" ", " ").split())
        text = SCHEME.sub("", ESCAPE.sub("", html.unescape(text)))
        text = EDGE.sub("", LEAD.sub("", text))
        text = " ".join(MARKUP.sub("", text).split())[:MAX_ITEM].strip()
        if text and text not in [t for t, _ in out]:
            out.append((text, entry.get("done") is True))
        if len(out) >= MAX_ITEMS:
            break
    return out


def accepted(
    intent: str,
    confidence: str,
    items: list[tuple[str, bool]],
    *,
    handwritten: bool = False,
) -> bool:
    """Whether a reading is a confident list of actions with entries. For a photo of
    a whiteboard, handwriting or a document (handwritten) medium confidence passes too
    with at least MEDIUM_ITEMS entries: doubt marks "(?)" and doodles make the model
    less sure of a plain to-do list (#465). Low never passes."""
    if intent != INTENT or not items:
        return False
    return confidence == HIGH or (
        handwritten and confidence == "medium" and len(items) >= MEDIUM_ITEMS
    )


def clean_due(raw: Any) -> str:
    """The date the page gives for its list, as the model answered: YYYY-MM-DD, or
    MM-DD when the page writes no year; else empty."""
    value = raw.strip() if isinstance(raw, str) else ""
    return value if DUE.fullmatch(value) else ""


def due_day(raw: Any, today: date) -> str | None:
    """A todo's due day (YYYY-MM-DD) from the model's due, or None when it gave none
    or an impossible date. A date with no year (MM-DD) is its next occurrence on or
    after today (29 February: the next leap year)."""
    value = clean_due(raw)
    if not value:
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        month, dom = int(value[:2]), int(value[3:])
        for year in range(today.year, today.year + 9):
            try:
                found = date(year, month, dom)
            except ValueError:
                continue
            if found >= today:
                return found.isoformat()
    except ValueError:
        pass
    return None


def set_due(store: Store, page_id: str, due: str) -> bool:
    """Give a todo the due date the page names, as a revision by Claude that revert
    undoes; whether it did. Nothing (False) unless the page is a todo with no due date
    yet: one the user dated is never changed."""
    try:
        page = store.page(page_id)
        if page["kind"] != "todo" or page.get("due"):
            return False
        done = store.edit_meta([page_id], CLAUDE, MCP, fields={"due": due})
    except (ConflictError, InvalidError, KeyError) as error:
        log.info("due date skipped: %s", error)
        return False
    return bool(done["pages"][0]["changed"])


def boxes(items: list[tuple[str, bool]]) -> str:
    return "\n".join(f"- [{'x' if done else ' '}] {text}" for text, done in items)


def append(
    store: Store,
    page_id: str,
    base_rev: int,
    items: list[tuple[str, bool]],
    *,
    whiteboard: bool = False,
) -> bool:
    """Append the entries as task boxes, below the page's text, as one revision by
    Claude; whether it did. It does nothing (False) unless, as it stands now, the page
    is not in the trash, is at base_rev (the revision Claude read: a later edit wins),
    is a note nobody filed (kind_fixed 0; whiteboard: or a whiteboard likewise, as photo
    ingest files one, which then becomes a todo) and has no task boxes. Run twice, the
    second time it finds the boxes and does nothing."""
    if not items:
        return False

    def change(conn: sqlite3.Connection, page: sqlite3.Row) -> tuple[str, str]:
        kinds = ("note", "whiteboard") if whiteboard else ("note",)
        if (
            not may_rekind(page["kind"], page["kind_fixed"], kinds)
            or tasks(page["body"])[1]
        ):
            return page["title"], page["body"]
        if page["kind"] == "whiteboard":  # ingest's guess, now a list: filed by boxes
            conn.execute("UPDATE page SET kind = 'note' WHERE id = ?", (page["id"],))
        body = page["body"].rstrip("\n")
        return page["title"], (body + "\n\n" if body else "") + boxes(items) + "\n"

    try:
        done = store.edit_text(
            page_id, CLAUDE, change, base_rev, fold=False, source=MCP
        )
    except ConflictError:
        log.info("task boxes skipped: page %s changed since it was read", page_id)
        return False
    except InvalidError as error:  # for instance, the page would be too big
        log.info("task boxes skipped: %s", error)
        return False
    return bool(done["changed"])
