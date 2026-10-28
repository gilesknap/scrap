"""Ordering search results by section (group:, #309): the PWA draws the sections
(web/src/groups.ts), the store orders by the section first, so the results a page of
the API returns never split one. The SQL functions here compute a page's section key
(text that sorts in the order the sections are shown, then in the order inside the
section); db.connect registers them. They mirror groups.ts and now.ts: a change to one
is a change to the other."""

import json
import sqlite3
import unicodedata
from datetime import date, timedelta
from typing import Any

from ..query import SUBTYPES, Query
from . import topics
from .todo import col

# Digits to their nines' complement, so a timestamp as text sorts newest first
NEWEST = str.maketrans("0123456789", "9876543210")
CLOSED = ("done", "cancelled")
LAST = "9"  # the section after all the others: Done, then not a section's key otherwise


def _closed(kind: str, fields: str) -> bool:
    """A todo or Later whose status ends it (statusOf and closed in status.ts)."""
    if kind not in ("todo", "consume"):
        return False
    status = json.loads(fields).get("status") if fields else None
    return str(status or "open") in CLOSED


def letter(title: str | None) -> str:
    """A title's first letter, A to Z (its accent dropped), else ~: last."""
    c = unicodedata.normalize("NFD", (title or "").strip())[:1].upper()
    return c if "A" <= c <= "Z" else "~"


def type_key(kind: str, fields: str) -> str:
    """A Later's section: its subtype's place (an unknown one reads), then Done."""
    if _closed(kind, fields):
        return LAST
    subtype = str(json.loads(fields or "{}").get("subtype") or "read")
    return str(SUBTYPES.index(subtype) if subtype in SUBTYPES else 0)


def sub_tag(tag: str, under: str) -> str | None:
    """The first segment of tag below under (person/family/x below person: family), or
    None if it is not below it."""
    prefix = f"{under.lower()}/"
    if not tag.lower().startswith(prefix):
        return None
    return tag[len(prefix) :].split("/")[0]


def _rank(priority: str | None) -> str:
    return {"high": "0", "medium": "1", "low": "2"}.get(priority or "", "3")


def now_key(
    kind: str, fields: str, due: str | None, priority: str | None,
    updated_at: str, today: str, ranked: int,
) -> str:  # fmt: skip
    """A page's place in Now (now.ts): Overdue, Today, High priority (dated or not,
    soonest due first), then Open; then Done. A dated todo never ranks below an
    undated one of its priority. ranked: each section in now.ts's own order, else the
    caller's."""
    if _closed(kind, fields):
        return LAST
    section = (
        0 if due and due < today
        else 1 if due == today
        else 2 if priority == "high"
        else 3
    )  # fmt: skip
    if not ranked:
        return str(section)
    recent, rank, when = updated_at.translate(NEWEST), _rank(priority), due or "~"
    order = (
        (when, rank, recent), (rank, recent), (when, recent), (rank, when, recent)
    )[section]  # fmt: skip
    return "|".join((str(section), *order))


def due_key(kind: str, fields: str, due: str | None, today: str) -> str:
    """A page's section by when due: Overdue, Today, Tomorrow, This week, Later, No
    date; Done last. Soonest first inside each."""
    if _closed(kind, fields):
        return LAST
    if not due:
        return f"5|{LAST}"
    week = (date.fromisoformat(today) + timedelta(days=7)).isoformat()
    tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    section = (
        0 if due < today
        else 1 if due == today
        else 2 if due == tomorrow
        else 3 if due <= week
        else 4
    )  # fmt: skip
    return f"{section}|{due}"


FUNCTIONS: dict[str, Any] = {
    "grp_letter": (1, letter), "grp_type": (2, type_key), "grp_sub": (2, sub_tag),
    "grp_now": (7, now_key), "grp_due": (4, due_key),
}  # fmt: skip


def use_areas(conn: sqlite3.Connection) -> None:
    """Register grp_area on a connection: a topic page's place among the areas, as
    topics.index orders them (the biggest area first, none last); any other page's is
    after them all. Per connection, as the areas are read now (group:area)."""
    rank: dict[str, int] = {}
    areas: dict[str | None, int] = {}
    for page_id, area in topics.areas(conn).items():  # already in the order shown
        rank[page_id] = areas.setdefault(area, len(areas))
    last = len(areas)
    conn.create_function("grp_area", 1, lambda page_id: rank.get(page_id, last))


def order(q: Query) -> tuple[str, list[Any]]:
    """The ORDER BY terms (with a trailing comma, or none) that put a query's pages in
    its group: sections, and the args their SQL takes. A tag section needs a tag:."""
    today = date.today().isoformat()
    ranked = int(q.sort is None)
    cols = "p.kind, p.fields"
    match q.group:
        case "letter":
            return "grp_letter(p.title), ", []
        case "area":  # use_areas registers it
            return "grp_area(p.id), ", []
        case "type":
            return f"grp_type({cols}), ", []
        case "now":
            return (
                f"grp_now({cols}, {col('due')}, {col('priority')}, p.updated_at,"
                " ?, ?), ",
                [today, ranked],
            )
        case "due":
            return f"grp_due({cols}, {col('due')}, ?), ", [today]
        case "tag":
            tags = [
                f.value.strip("/") for f in q.filters if f.key == "tag" and not f.neg
            ]
            if tags and tags[0]:
                sub = (
                    "(SELECT min(grp_sub(t.tag, ?)) FROM tag t WHERE t.page_id = p.id)"
                )
                return f"{sub} IS NULL, {sub}, ", [tags[0], tags[0]]
    return "", []
