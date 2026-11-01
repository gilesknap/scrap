"""Bringing the site in line with scrap's copies (docs/reference/public-site.md,
"scrap's copies" and "Reconciling"): pushing the derived units whose digest changed,
finding the copies to prune, and the reconcile pass. The Publisher calls these under
its lock; nothing here locks."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..store import Store
from . import derived
from .client import Receiver
from .errors import ReceiverError
from .kept import Kept
from .pages import states
from .unit import digest

__all__ = ["FIXED", "Summary", "push_derived", "reconcile", "stale_copies"]

FIXED = ("home", "pagefind", "assets")  # the units every site has
log = logging.getLogger(__name__)


def push_derived(
    kept: Kept, receiver: Receiver, units: dict[str, dict[str, bytes]]
) -> list[str]:
    """Push each derived unit whose digest differs from the one scrap last pushed,
    and delete the tag units no public page has any more; the units pushed.
    ReceiverError if the receiver refuses or cannot be reached."""
    pushed = []
    stored = kept.digests()
    for name in sorted(units):
        files = units[name]
        if stored.get(name) != digest(files):
            kept.set_digest(name, receiver.put(name, files))
            pushed.append(name)
    for name in sorted(stored):
        if name.startswith("t/") and name not in units:
            receiver.delete(name)
            kept.drop_digest(name)
    return pushed


def stale_copies(store: Store, kept: Kept, ids: set[str] | None = None) -> list[str]:
    """The kept copies the site must no longer hold (of the pages ids, else every
    page's): their page is gone, not public, in the trash or under another slug; with
    ids None, damaged copies too."""
    metas = {slug: kept.meta(slug) for slug in kept.slugs()}
    owners = {s: str(m.get("id")) if m else None for s, m in metas.items()}
    wanted = [o for o in owners.values() if o and (ids is None or o in ids)]
    pages = states(store, wanted)
    stale = []
    for slug, owner in owners.items():
        if ids is not None and owner not in ids:
            continue
        page = pages.get(owner or "")
        if page is None or not page.live or page.slug != slug:
            stale.append(slug)
        elif ids is None and kept.damaged(slug):
            log.warning("publish: the kept copy of p/%s is damaged: pruned", slug)
            stale.append(slug)
    return stale


@dataclass
class Summary:
    """What a reconcile did."""

    pruned: list[str] = field(default_factory=list)
    pushed: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    search_failed: bool = False  # Pagefind failed: the site keeps its last index


def reconcile(
    store: Store, kept: Kept, receiver: Receiver | None, static: Path
) -> Summary:
    """One pass: prune the copies of pages that are not public, in the trash or
    damaged (and their units); build every derived unit fresh from the copies left;
    push each unit the receiver's manifest lacks or holds otherwise (a page unit from
    its kept bytes, a derived one from the fresh build); then sync, deleting any
    stray. Without a receiver (publishing off) only the prune runs. A unit the
    receiver refuses is logged and left to the next pass; an unreachable receiver
    ends the pass (ReceiverError)."""
    out = Summary()
    kept.clean()
    for slug in stale_copies(store, kept):
        kept.delete(slug)
        out.pruned.append(f"p/{slug}")
    if receiver is None:
        return out
    units = derived.build(kept, static)
    out.search_failed = derived.pending(units)
    for unit in out.pruned:  # sync would too; deleting first frees the quota
        _try(receiver.delete, unit, out)
    held = receiver.manifest().get("units") or {}
    pages = [f"p/{slug}" for slug in kept.slugs()]
    for name in sorted([*pages, *units]):
        # a page's bytes are read one unit at a time: the site may be large
        files = units[name] if name in units else kept.files(name[2:])
        dig = digest(files)
        if (held.get(name) or {}).get("digest") == dig:
            if kept.digest(name) != dig:
                kept.set_digest(name, dig)
            continue
        if _try(receiver.put, name, out, files) is not None:
            kept.set_digest(name, dig)
            out.pushed.append(name)
    keep = sorted({*pages, *units, *FIXED})  # a unit not built keeps its last
    out.deleted = receiver.sync(keep)
    for name in kept.digests():
        if name not in keep:
            kept.drop_digest(name)
    return out


def _try(call, unit: str, out: Summary, *args):  # type: ignore[no-untyped-def]
    """call(unit, *args); a refusal logged (and listed in out.failed) and None, an
    unreachable receiver raised."""
    try:
        return call(unit, *args) or True
    except ReceiverError as e:
        if e.code == "unreachable":
            raise
        log.warning("publish: reconcile: %s: %s", unit, e)
        out.failed.append(unit)
        return None
