"""``scrap gc`` gathers orphaned files onto one review page a month (#124).

An orphan is a file of a capture (a photo, a PDF) that no page shows any more: the
user deleted its last embed or link. gc never deletes one. It appends each to the
month's open todo page, "Orphaned assets YYYY-MM", with Claude's description and where
it was last shown, and the user reviews that page: cut an item into another page to
keep it there, or delete the page.

A file is gathered when, all read from the data (nothing records what was gathered):

- no page's current text mentions its address (``store.body_refs``), the trash's too:
  so one already on an orphan page, or on a trashed one, is never gathered again;
- every capture that holds it is on a page not in the trash whose text once showed it
  (a file never embedded, such as an older page's photo or a PDF, is still listed
  below its page's text);
- the page it went from last is not a review page (one whose capture's source is
  ``gc``, however it is titled now): an item cut out of one and pasted
  nowhere is reviewed, an item cut into another page and later deleted there is an
  orphan again;
- it went longer ago than the grace period, so a line cut and pasted back is left be.

The page is a todo, due 7 days after it is made, and written as the user's (not over
MCP), so it can be edited and deleted freely. Later orphans that month are appended to
it, leaving its due date alone. Once it is ticked done (or cancelled) or deleted, the
next orphans that month start a fresh one. Its capture is a ``file`` capture with no
files, so Claude's enrichment leaves it alone (``store.NOT_BY_INGEST``).
"""

import logging
import os
import re
import sqlite3
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .store import MAX_PAGE, Store, body_refs, new_ulid
from .store.health import REVIEW  # a review page: one gc made (its capture's source)

__all__ = ["DUE_DAYS", "TITLE", "Gathered", "Orphan", "clock", "find", "gather"]

log = logging.getLogger(__name__)

DUE_DAYS = 7  # an orphan page's due date, after it is made
TITLE = "Orphaned assets {month}"  # month: YYYY-MM
AUTHOR = "scrap gc"  # its revisions' author; its capture's source is "gc"
SOURCE = "gc"
ADDRESS = "/api/blobs/"


def clock() -> datetime:
    """Now, in UTC (tests replace it)."""
    return datetime.now(UTC)


@dataclass
class Orphan:
    sha: str
    mime: str
    filename: str | None
    slug: str  # the page it went from last
    title: str
    removed_at: str  # the revision that took it out
    description: str | None  # Claude's
    drawing: bool


@dataclass
class Gathered:
    count: int = 0
    pages: list[str] = field(default_factory=list)  # the slugs written to
    created: bool = False  # a new month page was made


def _orphan_pages(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT id FROM page p WHERE " + REVIEW.format(p="p"))
    }


def find(conn: sqlite3.Connection, cutoff: str) -> list[Orphan]:
    """The orphans (see the module) that went before cutoff (a stored timestamp),
    oldest first; read on conn, in its transaction if one is open."""
    holders: dict[str, set[str]] = {}  # sha: the pages of the captures that hold it
    mimes: dict[str, tuple[str, str | None]] = {}
    for sha, page_id, mime, name in conn.execute(
        "SELECT cb.sha256, c.page_id, b.mime, cb.filename FROM capture_blob cb"
        " JOIN capture c ON c.id = cb.capture_id JOIN blob b USING (sha256)"
    ):
        holders.setdefault(sha, set()).add(page_id)
        if sha not in mimes or (name and not mimes[sha][1]):
            mimes[sha] = (mime, name)
    shown: set[str] = set()
    trashed: set[str] = set()
    for page_id, body, deleted in conn.execute("SELECT id, body, deleted_at FROM page"):
        shown |= body_refs(body)
        if deleted:
            trashed.add(page_id)
    candidates = {
        sha
        for sha, pages in holders.items()
        if sha not in shown and not pages & trashed
    }
    if not candidates:
        return []

    # Walk every page's revisions: which pages ever showed each candidate, and the
    # last time one was taken out of a page (the first revision without it after one
    # with it).
    ever: dict[str, set[str]] = {}
    last: dict[str, tuple[str, str]] = {}  # sha: (removed_at, page_id)
    page, before = None, set()
    for page_id, body, created in conn.execute(
        "SELECT page_id, body, created_at FROM page_rev ORDER BY page_id, rev"
    ):
        if page_id != page:
            page, before = page_id, set()
        refs = body_refs(body) & candidates if ADDRESS in body else set()
        for sha in before - refs:
            if sha not in last or created > last[sha][0]:
                last[sha] = (created, page_id)
        for sha in refs:
            ever.setdefault(sha, set()).add(page_id)
        before = refs

    orphan_pages = _orphan_pages(conn)
    found: list[Orphan] = []
    for sha in candidates:
        if sha not in last or not holders[sha] <= ever.get(sha, set()):
            continue  # still listed below a page that never embedded it
        removed_at, page_id = last[sha]
        if page_id in orphan_pages or removed_at >= cutoff:
            continue
        slug, title = conn.execute(
            "SELECT slug, title FROM page WHERE id = ?", (page_id,)
        ).fetchone()
        derived = dict(
            conn.execute(
                "SELECT kind, text FROM derived WHERE source_sha256 = ?"
                " AND superseded_at IS NULL AND kind IN ('description', 'excalidraw')"
                " ORDER BY created_at",
                (sha,),
            )
        )
        mime, name = mimes[sha]
        found.append(
            Orphan(sha, mime, name, slug, title, removed_at,
                   derived.get("description"), "excalidraw" in derived)
        )  # fmt: skip
    return sorted(found, key=lambda o: (o.removed_at, o.sha))


def _label(text: str) -> str:
    """Text safe as a link's or page link's label: no brackets, pipes or newlines."""
    return " ".join(re.sub(r"[\[\]|]", " ", text).split()) or "file"


def entry(o: Orphan) -> str:
    """One orphan as the page shows it: its embed (a link, for a file that is not an
    image), where it was last shown, and Claude's description."""
    if o.mime.startswith("image/"):
        show = f"![](/api/blobs/{o.sha}/preview?size=2048)"
    else:
        show = f"[{_label(o.filename or o.mime)}](/api/blobs/{o.sha})"
    when = datetime.fromisoformat(o.removed_at).strftime("%Y-%m-%d %H:%M UTC")
    where = f"From [[{o.slug}|{_label(o.title)}]], last shown {when}."
    if o.drawing:
        where += " It has a drawing, kept with the file."
    parts = [show, where]
    if o.description and o.description.strip():
        quoted = "\n".join(
            f"> {line}".rstrip() for line in o.description.strip().splitlines()
        )
        parts.append(f"> Claude's description:\n>\n{quoted}")
    return "\n\n".join(parts)


def _intro(today: str) -> str:
    return (
        f"Files no page shows any more, gathered by scrap gc (from {today}). Cut one"
        " into another page to keep it there. Delete this page once you have looked"
        " through it: its files go to the trash with it. Tick it done and later"
        " orphans start a new page."
    )


def _current(conn: sqlite3.Connection, month: str) -> tuple[str, int, str] | None:
    """The month's (YYYY-MM) open review page, by its gc capture's date, however it
    is titled: (id, rev, body), the newest if several."""
    row = conn.execute(
        "SELECT p.id, p.body, (SELECT max(rev) FROM page_rev WHERE page_id = p.id)"
        " FROM page p JOIN capture c ON c.page_id = p.id AND c.source = 'gc'"
        " WHERE substr(c.created_at, 1, 7) = ? AND p.kind = 'todo'"
        " AND p.deleted_at IS NULL"
        " AND coalesce(json_extract(p.fields, '$.status'), 'open')"
        " NOT IN ('done', 'cancelled') ORDER BY c.created_at DESC, p.id DESC LIMIT 1",
        (month,),
    ).fetchone()
    return (row[0], row[2], row[1]) if row else None


def _create(store: Store, title: str, body: str, when: datetime) -> str:
    stamp = when.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    c = {
        "id": new_ulid(), "kind": "file", "text": None, "url": None,
        "source": SOURCE, "created_at": stamp, "page_kind": "todo",
        "fields": {"status": "open"}, "title": title, "body": body, "tags": [],
        "due": (when + timedelta(days=DUE_DAYS)).date().isoformat(),
        "priority": None, "snoozed_until": None,
    }  # fmt: skip
    ref, _ = store.capture(c, [], AUTHOR)
    return ref["slug"]


def gather(store: Store, cutoff: str) -> Gathered:
    """Append every orphan (see find) to the month's open orphan page, making one if
    there is none (or when it is full). Raises sqlite3.Error, ConflictError if that
    page was edited meanwhile, or InvalidError for an entry past a page's cap."""
    when = clock()
    month = when.strftime("%Y-%m")
    title = TITLE.format(month=month)
    with store.connect() as conn:  # one read snapshot of both, no write lock held
        conn.execute("BEGIN")
        try:
            orphans = find(conn, cutoff)
            target = _current(conn, month)
        finally:
            conn.execute("COMMIT")
    result = Gathered(len(orphans))
    intro = _intro(when.date().isoformat())

    def write(body: str) -> None:
        if target:
            page = store.update_page(target[0], target[1], None, body, AUTHOR)
            result.pages.append(page["slug"])
        else:
            result.pages.append(_create(store, title, body, when))
            result.created = True

    body, pending = (target[2].rstrip() if target else intro), 0
    for item in orphans:
        longer = f"{body}\n\n{entry(item)}"
        if len(longer.encode()) > MAX_PAGE and (pending or target):
            if pending:  # this page is full: the rest go on a new one
                write(body)
            target, body, pending = None, intro, 0
            longer = f"{body}\n\n{entry(item)}"
        body, pending = longer, pending + 1
    if pending:
        write(body)
    if result.created:
        notify(f"scrap gc gathered orphaned files onto {title}. Review it in scrap.")
    return result


def notify(message: str) -> None:
    """POST one fixed line to SCRAP_NOTIFY_URL, if set (as ingest's pause alerts)."""
    url = os.environ.get("SCRAP_NOTIFY_URL")
    if not url:
        return
    try:
        urllib.request.urlopen(url, message.encode(), timeout=10).close()
    except Exception:  # noqa: BLE001  a lost notice must not fail gc
        log.warning("orphan page notification failed")
