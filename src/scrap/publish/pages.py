"""What publishing reads of the store: a page's state (public, in the trash, its
revision, text, tags and attached files), the public pages, and the pages that refer
to a page."""

import sqlite3
from dataclasses import dataclass

from ..store import NoSuchPage, Store, writeups

__all__ = ["Page", "linking", "public_pages", "public_slugs", "state", "states"]

COLUMNS = (
    "SELECT id, slug, title, body, public, deleted_at,"
    " (SELECT max(rev) FROM page_rev WHERE page_id = page.id) AS rev FROM page"
)
PUBLIC = "public = 1 AND deleted_at IS NULL"


@dataclass(frozen=True)
class Page:
    id: str
    slug: str
    title: str
    body: str
    public: bool
    trashed: bool
    rev: int
    tags: tuple[str, ...]
    attached: frozenset[str] = frozenset()  # its captures' files, by sha
    drawings: frozenset[str] = frozenset()  # its photos' current drawings, by id (#520)

    @property
    def live(self) -> bool:
        """Public and not in the trash: a page the site may hold."""
        return self.public and not self.trashed


def _page(conn: sqlite3.Connection, row: sqlite3.Row) -> Page:
    tags = conn.execute("SELECT tag FROM tag WHERE page_id = ? ORDER BY tag", (row[0],))
    tags = tuple(t[0] for t in tags)
    files = conn.execute(
        "SELECT sha256 FROM capture_blob JOIN capture ON capture.id = capture_id"
        " WHERE page_id = ?", (row[0],),
    )  # fmt: skip
    attached = frozenset(f[0] for f in files)
    drawings = conn.execute(
        "SELECT d.id FROM derived d JOIN capture c ON c.id = d.capture_id"
        " WHERE c.page_id = ? AND d.kind = 'excalidraw' AND d.superseded_at IS NULL",
        (row[0],),
    )  # fmt: skip
    return Page(row["id"], row["slug"], row["title"], row["body"],
                bool(row["public"]), row["deleted_at"] is not None, row["rev"] or 0,
                tags, attached, frozenset(str(d[0]) for d in drawings))  # fmt: skip


def state(store: Store, key: str) -> Page:
    """A page by id or slug, the trash's too; NoSuchPage if there is none."""
    with store.connect() as conn:
        row = conn.execute(f"{COLUMNS} WHERE id = ? OR slug = ?", (key, key))
        found = row.fetchone()
        if found is None:
            raise NoSuchPage(key)
        return _page(conn, found)


def states(store: Store, ids: list[str]) -> dict[str, Page]:
    """The pages of these ids that still exist, by id."""
    out = {}
    with store.connect() as conn:
        for page_id in dict.fromkeys(ids):
            row = conn.execute(f"{COLUMNS} WHERE id = ?", (page_id,)).fetchone()
            if row is not None:
                out[page_id] = _page(conn, row)
    return out


def public_slugs(store: Store) -> set[str]:
    """The slugs of the public pages not in the trash."""
    with store.connect() as conn:
        return {r[0] for r in conn.execute(f"SELECT slug FROM page WHERE {PUBLIC}")}


def public_pages(store: Store) -> list[dict[str, str]]:
    """The public pages not in the trash, {id, slug, title}, by title then slug."""
    with store.connect() as conn:
        rows = conn.execute(
            f"SELECT id, slug, title FROM page WHERE {PUBLIC} ORDER BY title, slug"
        )
        return [dict(r) for r in rows]


def linking(store: Store, slug: str) -> set[str]:
    """The ids of the pages that refer to the page slug, from scrap's own link data
    (not the published HTML, where a link to a private page is only a label): those
    whose text or current write-up links to it, and those related to it either way
    (Claude's picks). For GET /api/public?links_to=."""
    found = {b["id"] for b in store.backlinks(slug)}
    with store.connect() as conn:
        found |= {w["id"] for w in writeups.backlinks(conn, slug)}
        row = conn.execute("SELECT id FROM page WHERE slug = ?", (slug,)).fetchone()
        if row is not None:
            found |= {r[0] for r in conn.execute(
                "SELECT other_id FROM related WHERE page_id = ?"
                " UNION SELECT page_id FROM related WHERE other_id = ?",
                (row[0], row[0]),
            )}  # fmt: skip
            found.discard(row[0])
    return found
