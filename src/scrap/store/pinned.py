"""The Pinned page (design: pinned searches and pages): one ordinary page, titled
Pinned with the slug `pinned`, whose body is a list of links the search screen shows
as a launcher. The slug is reserved: ensure_pinned makes the page at most once, or
brings it back from the trash, so two first pins at once, or a page the owner already
called pinned, never leave a second one. Claude does not read it
(roles.NOT_PINNED: should_enrich, backfill and the related pass).
"""

from typing import Any

from .constants import PINNED_SLUG, REV_INSERT
from .db import transaction
from .helpers import new_ulid, now
from .pages import PagesMixin
from .trash import restore_in


class PinnedMixin(PagesMixin):
    def ensure_pinned(self, author: str) -> dict[str, Any]:
        """The Pinned page, made if there is none (from the trash, if it is there):
        the page as GET /api/pages/pinned has it. Safe to call twice at once."""
        with self.connect() as conn, transaction(conn):  # one writer at a time
            row = conn.execute(
                "SELECT id, deleted_at FROM page WHERE slug = ?", (PINNED_SLUG,)
            ).fetchone()
            stamp = now()
            if row is None:
                page_id = new_ulid()
                title, body = "Pinned", "# Pinned\n\n"
                conn.execute(
                    "INSERT INTO page (id, slug, title, body, kind, kind_fixed,"
                    " fields, created_at, updated_at, made_by)"
                    " VALUES (?, ?, ?, ?, 'note', 1, '{}', ?, ?, 'human')",
                    (page_id, PINNED_SLUG, title, body, stamp, stamp),
                )
                conn.execute(
                    REV_INSERT, (page_id, 1, title, body, author, "web", stamp)
                )
                self.reindex(conn, page_id)
            else:
                page_id = row["id"]
                if row["deleted_at"]:
                    restore_in(conn, page_id)
            return self.page_in(conn, page_id)
