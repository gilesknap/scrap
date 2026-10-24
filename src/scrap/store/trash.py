"""The trash."""

from typing import Any

from .core import Core
from .db import _rows
from .errors import NoSuchPage
from .helpers import now


class TrashMixin(Core):
    def trash(self, limit: int) -> list[dict[str, Any]]:
        """The pages in the trash, most recently deleted first."""
        with self.connect() as conn:
            return _rows(
                conn,
                "SELECT id, slug, title, kind, deleted_at, updated_at FROM page"
                " WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC, id DESC"
                " LIMIT ?",
                limit,
            )

    def trashed(self, key: str) -> dict[str, Any] | None:
        """A page in the trash by id or slug (id, slug, title, kind, deleted_at),
        None if there is none."""
        with self.connect() as conn:
            rows = _rows(
                conn,
                "SELECT id, slug, title, kind, deleted_at FROM page"
                " WHERE (id = ? OR slug = ?) AND deleted_at IS NOT NULL",
                key, key,
            )  # fmt: skip
        return rows[0] if rows else None

    def delete_page(self, key: str, undo: bool = False) -> None:
        """Move a page to the trash (or back); captures and files stay until a purge."""
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE page SET deleted_at = ? WHERE (id = ? OR slug = ?)"
                f" AND deleted_at IS {'NOT' if undo else ''} NULL",
                (None if undo else now(), key, key),
            )
        if cur.rowcount == 0:
            raise NoSuchPage(key)
