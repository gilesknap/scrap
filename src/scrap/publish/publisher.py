"""Publishing (ADR 43, docs/reference/public-site.md): the Publisher holds scrap's one
lock over every publish, unpublish and reconcile, so they never interleave, and runs
the reconcile loop (at start and every RECONCILE_EVERY seconds; after a failure,
at start too, again after RETRY_FIRST seconds, doubling up to RECONCILE_EVERY) while
publishing is on.

- publish: read the page again under the lock and refuse unless it is public, not in
  the trash, already published or confirmed, and at base_rev; check the HTML, swap
  its placeholders, push its unit, keep the copy; then, unless deferred, push the
  derived units that changed.
- settle (an unpublish): after a flag change or a trash has committed, delete the
  kept copy of each such page that may no longer be public, then its unit, then
  push the derived units again. A receiver that cannot be reached leaves it
  "pending": the copy is gone, so the next reconcile removes the unit.

Nothing fails once something has committed (the page's unit pushed, or the flag
change or trash before a settle): any error after that is logged, and the answer
says "pending" for what the next reconcile finishes.
"""

import logging
import threading
from pathlib import Path
from typing import Any

from ..store import Store, body_refs, now
from . import derived, pages
from .checker import check
from .client import Receiver
from .diagrams import page_diagrams
from .drawings import page_drawings
from .errors import (
    CheckError,
    NotConfigured,
    NotPublic,
    PublishFailed,
    ReceiverError,
    Stale,
    Unconfirmed,
)
from .files import MAX_UNIT, page_files
from .kept import Kept
from .push import push_derived, reconcile, stale_copies
from .rewrite import swap
from .settings import enabled, page_url, publish_site, publish_to, static_dir, token

__all__ = ["RECONCILE_EVERY", "RETRY_FIRST", "Publisher", "backoff"]

RECONCILE_EVERY = 600.0  # seconds
RETRY_FIRST = 30.0  # after a failed reconcile; doubling, up to RECONCILE_EVERY
PENDING = "pending"
log = logging.getLogger(__name__)


def backoff(failures: int, every: float, retry: float) -> float:
    """Seconds to the next reconcile after this many failures in a row: every after
    a success, else retry, doubling, up to every.

    >>> [backoff(n, 600, 30) for n in range(7)]
    [600, 30, 60, 120, 240, 480, 600]
    """
    if failures == 0:
        return every
    return min(retry * 2 ** (failures - 1), every)


class Publisher:
    def __init__(self, store: Store, static: Path | None = None) -> None:
        self.store = store
        self.kept = Kept(store.dir / "cache" / "publish")
        self.static = static  # the PWA build's public/ folder (default: static_dir)
        self.lock = threading.RLock()
        self.last: dict[str, Any] = {"at": None, "ok": None, "error": None}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _receiver(self) -> Receiver:
        to, key = publish_to(), token()
        if to is None or key is None:
            raise NotConfigured()
        return Receiver(to, key)

    def _units(self) -> dict[str, dict[str, bytes]]:
        return derived.build(self.kept, self.static or static_dir())

    def publish(
        self, key: str, html: str, base_rev: int, defer: bool,
        confirmed: bool = False, drawings: dict[str, str] | None = None,
        diagrams: dict[str, tuple[str, str]] | None = None,
    ) -> dict:  # fmt: skip
        """Publish a page from the PWA's publish mode (see the module docstring):
        {url, published_at, files}; NotPublic, Unconfirmed (a first publish, with no
        kept copy, needs confirmed), Stale, CheckError, PublishFailed or
        NotConfigured otherwise. drawings: each drawing's SVG the page shows, by
        its id (#520), cleaned by publish.drawings; diagrams: each Mermaid
        diagram's (light, dark) SVGs, by its key (#525), cleaned by
        publish.diagrams."""
        if not enabled():
            raise NotConfigured()
        with self.lock:
            page = pages.state(self.store, key)
            if not page.live:
                raise NotPublic(
                    "the page is in the trash" if page.trashed
                    else "the page is not public"
                )  # fmt: skip
            if not confirmed and self.published_at(page.id, page.slug) is None:
                raise Unconfirmed()
            if base_rev != page.rev:
                raise Stale(page.rev)
            is_public = pages.public_slugs(self.store).__contains__
            checked = check(html, is_public)
            if gone := [t for t in checked.tags if t not in page.tags]:
                raise CheckError(
                    f"Not published: the page no longer has the tag {gone[0]!r}.",
                    "stale_tags",
                )
            on_page = body_refs(page.body) | page.attached  # its text's, its own
            site = publish_site()
            drawn = page_drawings(
                self.store, checked, drawings or {}, page.drawings, on_page,
                is_public, site,
            )  # fmt: skip
            charts = page_diagrams(checked, diagrams or {})
            files = page_files(
                self.store, page.slug, checked.blobs, on_page, len(html.encode()),
                drawn, charts,
            )  # fmt: skip
            unit = {"index.html": swap(html, page.slug, files.names, site).encode()}
            unit |= files.data
            if sum(len(v) for v in unit.values()) > MAX_UNIT:
                raise CheckError(
                    f"Not published: the page and its files are over"
                    f" {MAX_UNIT // 2**20} MiB.",
                    "unit_too_large",
                )
            meta = {
                "id": page.id, "title": page.title, "tags": list(page.tags),
                "published_at": now(),
            }  # fmt: skip
            with self._receiver() as receiver:
                try:
                    dig = receiver.put(f"p/{page.slug}", unit)
                except ReceiverError as e:
                    raise PublishFailed(e.code) from None
                out: dict[str, Any] = {
                    "url": page_url(page.slug),
                    "published_at": meta["published_at"],
                    "files": len(files.data),
                }
                try:  # the page is out: nothing after this fails the publish
                    self.kept.write(page.slug, unit, meta, dig)
                    if not defer:
                        self._settle_slugs(receiver, self._others(page))
                        units = self._units()
                        push_derived(self.kept, receiver, units)
                        if derived.pending(units):  # Pagefind failed
                            out["derived"] = PENDING
                except Exception:  # noqa: BLE001  reconcile does the rest
                    log.exception(
                        "publish: p/%s is out; the rest is pending", page.slug
                    )
                    out["derived"] = PENDING
            return out

    def _others(self, page: pages.Page) -> list[str]:
        """Copies of this page under another slug (it was renamed): to go."""
        return [
            s for s in self.kept.slugs()
            if s != page.slug and (self.kept.meta(s) or {}).get("id") == page.id
        ]  # fmt: skip

    def _settle_slugs(self, receiver: Receiver | None, slugs: list[str]) -> None:
        for slug in slugs:  # the copy first: a failed DELETE leaves it to reconcile
            self.kept.delete(slug)
        if receiver is not None:
            for slug in slugs:
                receiver.delete(f"p/{slug}")

    def settle(self, ids: list[str]) -> str | None:
        """Unpublish each of these pages that has a kept copy but may no longer be
        public (made private, put in the trash, gone), after the change committed:
        "pending" if the receiver could not be told (reconcile finishes it), else
        None."""
        with self.lock:
            stale: list[str] = []
            try:  # the change has committed: never fail it now
                stale = stale_copies(self.store, self.kept, set(ids))
                if not stale:
                    return None
                if not enabled():
                    self._settle_slugs(None, stale)
                    return None
                with self._receiver() as receiver:
                    self._settle_slugs(receiver, stale)
                    units = self._units()
                    push_derived(self.kept, receiver, units)
                if derived.pending(units):  # the page is gone; search is not rebuilt
                    return PENDING
            except ReceiverError as e:
                log.warning("publish: unpublishing %s is pending: %s", stale or ids, e)
                return PENDING
            except Exception:  # noqa: BLE001  reconcile finishes it
                log.exception("publish: unpublishing %s is pending", stale or ids)
                return PENDING
            return None

    def rebuild(self) -> dict[str, Any]:
        """Build home, the tag units, pagefind and assets once and push those whose
        digest changed (after a Refresh all's deferred publishes): {units: [those
        pushed]}, with "derived": "pending" if Pagefind failed (the site keeps its
        last index)."""
        if not enabled():
            raise NotConfigured()
        with self.lock, self._receiver() as receiver:
            units = self._units()
            try:
                out: dict[str, Any] = {
                    "units": push_derived(self.kept, receiver, units)
                }
            except ReceiverError as e:
                raise PublishFailed(e.code) from None
            if derived.pending(units):
                out["derived"] = PENDING
            return out

    def reconcile(self) -> None:
        """One reconcile pass (push.reconcile) under the lock, its outcome kept for
        the health checks."""
        with self.lock:
            try:
                if enabled():
                    with self._receiver() as receiver:
                        done = reconcile(
                            self.store, self.kept, receiver,
                            self.static or static_dir(),
                        )  # fmt: skip
                else:
                    done = reconcile(self.store, self.kept, None, Path())
                error = f"refused: {', '.join(done.failed)}" if done.failed else None
                if done.search_failed:
                    error = "the search index could not be built" + (
                        f"; {error}" if error else ""
                    )
            except ReceiverError as e:
                error = str(e)
            self.last = {"at": now(), "ok": error is None, "error": error}
            if error:
                log.warning("publish: reconcile: %s", error)

    # What the API and MCP read
    def published_at(self, page_id: str, slug: str) -> str | None:
        """When a page was last published: from its kept copy, None if there is
        none (never published, or unpublished)."""
        meta = self.kept.meta(slug)
        if meta is None or meta.get("id") != page_id:
            return None
        return meta.get("published_at")

    def public(self, links_to: str | None = None) -> list[dict[str, Any]]:
        """The public pages not in the trash, {id, slug, title, published_at}; with
        links_to, only those that refer to that slug (pages.linking: scrap's own link
        data, so a link the site shows as a label counts)."""
        out = []
        wanted = None if links_to is None else pages.linking(self.store, links_to)
        for row in pages.public_pages(self.store):
            if wanted is not None and row["id"] not in wanted:
                continue
            meta = self.kept.meta(row["slug"])
            if meta is not None and meta.get("id") != row["id"]:
                meta = None
            out.append({**row, "published_at": (meta or {}).get("published_at")})
        return out

    def health(self) -> dict[str, Any]:
        """The publish block of /healthz and /api/health (never a failure)."""
        return {
            "enabled": enabled(),
            "site": publish_site(),
            "pages": len(self.kept.slugs()),
            "last_reconcile": self.last["at"],
            "ok": self.last["ok"],
            "error": self.last["error"],
        }

    # The reconcile loop, while publishing is on (the app's lifespan)
    def start(self, every: float = RECONCILE_EVERY, retry: float = RETRY_FIRST) -> None:
        if self._thread is not None:
            return
        self._stop.clear()

        def loop() -> None:
            failures = 0
            while not self._stop.is_set():
                try:
                    self.reconcile()
                    ok = bool(self.last["ok"])
                except Exception:  # noqa: BLE001  the loop must keep going
                    log.exception("publish: reconcile failed")
                    ok = False
                failures = 0 if ok else failures + 1
                self._stop.wait(backoff(failures, every, retry))

        self._thread = threading.Thread(target=loop, name="publish", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
            self._thread = None
