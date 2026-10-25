"""Enrich: what the owner does with a board page's write-up (#256): regenerate it,
steer the next one with guidance, list its versions and restore one. Nobody edits a
write-up's text: a version is only ever made by Claude, or copied by a restore."""

from typing import Any

from ..store import (
    ConflictError,
    InvalidError,
    NotFoundError,
    Store,
    now,
    queue_writeup,
    transaction,
    writeups,
)
from .constants import MAX_GUIDANCE


class StaleWriteupError(ConflictError):
    """The write-up was changed since this view of it."""


def regenerate(store: Store, key: str) -> dict[str, Any]:
    """Queue a board page's write-up again (Regenerate), with the guidance as it is
    when it runs; the page as it is then. InvalidError if it has no board image."""
    with store.connect() as conn, transaction(conn):
        page = store._page_row(conn, key)  # noqa: SLF001  one transaction
        if not writeups.has_board(conn, page["id"]):
            raise InvalidError("only a whiteboard or diagram page has a write-up")
        queue_writeup(conn, page["id"])
        return store.page_in(conn, page["id"])


def set_guidance(
    store: Store, key: str, text: str | None, author: str
) -> dict[str, Any]:
    """Keep the owner's guidance for a page's next write-up (empty: none); the page.
    It is used by the next one made, and kept with that version."""
    if text is not None and len(text) > MAX_GUIDANCE:
        raise InvalidError(f"guidance is at most {MAX_GUIDANCE} characters")
    with store.connect() as conn, transaction(conn):
        page = store._page_row(conn, key)  # noqa: SLF001  one transaction
        writeups.set_guidance(conn, page["id"], text, author, now())
        return store.page_in(conn, page["id"])


def versions(store: Store, key: str) -> list[dict[str, Any]]:
    """Every write-up of a page, newest first, with its text."""
    with store.connect() as conn:
        page = store._page_row(conn, key)  # noqa: SLF001
        return writeups.versions(conn, page["id"])


def restore(store: Store, key: str, version: int, base: int) -> dict[str, Any]:
    """Make an old write-up current again, as a new copy of it (versions never
    change); the page. base must be the current version (else StaleWriteupError,
    409), so a stale list cannot restore over a newer one; NotFoundError (404) if
    there is no such version."""
    with store.connect() as conn, transaction(conn):
        page = store._page_row(conn, key)  # noqa: SLF001  one transaction
        up = writeups.current(conn, page["id"])
        if up is None or up["version"] != base:
            raise StaleWriteupError(up and up["version"])
        old = next(
            (v for v in writeups.versions(conn, page["id"]) if v["version"] == version),
            None,
        )
        if old is None:
            raise NotFoundError(f"no version {version}")
        writeups.put(
            conn, page["id"], now(), producer=old["producer"], run_id=old["run_id"],
            prompt_version=old["prompt_version"], summary=old["summary"],
            text=old["text"], guidance=old["guidance"], restored_from=version,
        )  # fmt: skip
        store.reindex(conn, page["id"])
        return store.page_in(conn, page["id"])
