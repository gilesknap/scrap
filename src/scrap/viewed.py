"""The page the user opened last (#452), for the MCP current_page tool. Scrap is one
user on one process, and this is a convenience, so it is a module-level value in memory
only: a restart forgets it (no schema, no migration). A multi-user version would need a
rework anyway."""

import threading

from .store import now

_lock = threading.Lock()
_last: tuple[str, str] | None = None  # (page id, when it was opened)


def record(page_id: str) -> str:
    """Remember page_id as the page opened now; when."""
    global _last
    when = now()
    with _lock:
        _last = (page_id, when)
    return when


def last() -> tuple[str, str] | None:
    """(page id, opened at) of the page opened last, else None."""
    with _lock:
        return _last


def clear() -> None:
    """Forget it (a restart does; tests use this)."""
    global _last
    with _lock:
        _last = None
