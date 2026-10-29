"""Planning an import, running it and reporting on it."""

import hashlib
import mimetypes
import posixpath
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..store import (
    MAX_PAGE,
    MAX_TAGS,
    BlobRef,
    InvalidError,
    Store,
    slug_base,
    upload_limit,
)
from ..store.constants import ENRICH_KINDS, PINNED_SLUG
from ..store.helpers import file_kind
from .linker import Linker, is_page
from .model import DRAWINGS, STORED, Page, Plan
from .reading import read, ulid
from .sources import RefusedError, Source

# What made a page that is not imported, and what the report says of it
NOT_IMPORTED = {
    "topic": "a Claude topic page (Claude makes them again)",
    "gc": "scrap gc's review page",
}


def import_tag(day: datetime | None = None) -> str:
    """The tag every page of an import gets: import/<the UTC date>."""
    return f"import/{(day or datetime.now(UTC)).date().isoformat()}"


def _pages(plan: Plan, src: Source) -> dict[str, Page]:
    pages: dict[str, Page] = {}
    for rel, entry in src.files.items():
        if not is_page(rel):
            continue
        try:
            data = src.read(rel, MAX_PAGE)
        except Exception as e:  # OSError, a bad zip entry (BadZipFile, zlib)
            plan.note("unreadable", rel, str(e)[:80] or type(e).__name__)
            continue
        if data is None:  # as for a page saved through the API (#62)
            plan.note("too large", rel, f"{entry.size:,} bytes, over {MAX_PAGE:,}")
            continue
        page = read(plan, rel, data, entry.mtime, MAX_TAGS - 1)
        if page.made_by in NOT_IMPORTED:
            plan.note("not imported", rel, NOT_IMPORTED[page.made_by])
            continue
        if page.made_by != "claude":
            page.made_by = "human"
        if plan.tag not in page.tags:  # an export of an import made today has it
            page.tags.append(plan.tag)
        # The same file twice gives the same id: a run again skips it
        page.cid = ulid(f"{rel}\0{hashlib.sha256(data).hexdigest()}")
        pages[rel] = page
    return pages


def plan(src: Source, store: Store, day: datetime | None = None) -> Plan:
    """Read the archive and work out every page, its slug and its rewritten text.
    Writes nothing. A page whose id (or, without one, whose path and bytes) is in the
    store already is not imported again, and slugs in use are avoided."""
    result = Plan(limit=upload_limit(), tag=import_tag(day))
    for folder in sorted(src.dropped):
        result.note("folder skipped", f"{folder}/")
    for rel in src.unsafe:
        result.note("not a plain file", rel, "a link or device, not read")
    pages = _pages(result, src)
    # Read only: a store with no database yet has nothing to match (none is made)
    with store.connect() if store.db.is_file() else nullcontext() as conn:
        taken = {r[0] for r in conn.execute("SELECT slug FROM page")} if conn else set()
        pinned = PINNED_SLUG in taken
        seen: set[str] = set()
        for page in pages.values():
            if page.id in seen:  # a file copied, id and all: a page of its own
                result.note("id used twice", page.path, "imported as a new page")
                page.id = None
            if page.id:
                seen.add(page.id)
            if conn is None:
                continue
            row = None
            if page.id:
                row = conn.execute(
                    "SELECT slug FROM page WHERE id = ?", (page.id,)
                ).fetchone()
            row = (
                row
                or conn.execute(
                    "SELECT p.slug FROM capture c JOIN page p ON p.id = c.page_id"
                    " WHERE c.id = ?",
                    (page.cid,),
                ).fetchone()
            )
            if row:
                page.slug, page.new, page.why = row[0], False, "here already"
            elif pinned and posixpath.basename(page.path) == f"{PINNED_SLUG}.md":
                page.new, page.why = False, "this store has its own Pinned page"
                page.slug = PINNED_SLUG
                result.note("not imported", page.path, page.why)
    # Slugs: from the file name, in path order
    for page in pages.values():
        if page.new:
            stem = posixpath.splitext(posixpath.basename(page.path))[0]
            base = slug_base(stem)
            slug, n = base, 1
            while slug in taken:
                n += 1
                slug = f"{base}-{n}"
            if slug != base:
                result.note("slug in use", page.path, f"now {slug}")
            page.slug = slug
            taken.add(slug)
    linker = Linker(result, src, pages)
    for page in pages.values():
        if page.new:
            page.body = linker.rewrite(page)
            linker.attach(page)
    used = {rel for page in pages.values() for rel in page.images + page.files}
    unused = [
        rel
        for rel in src.files
        if not is_page(rel)
        and rel not in used
        and not (STORED.fullmatch(rel) and rel.endswith(DRAWINGS))  # _claude's
    ]
    for rel in unused:
        result.note("file not used by a new page", rel)
    result.pages = list(pages.values())
    return result


@dataclass
class Done:
    """What a run did."""

    new: int = 0
    skipped: int = 0  # here already
    enrich: int = 0  # pages queued for Claude to tag and summarise
    photos: int = 0  # photos queued for Claude to read
    files: int = 0  # PDFs and text files queued to be read locally (free)


def run(
    store: Store,
    src: Source,
    plan: Plan,
    author: str = "import",
    enrich: bool = False,
    photos: bool = False,
) -> Done:
    """Import the planned pages that are not here yet. enrich: queue each new page
    that enrich reads (a note, todo or read, not a photo or file page) for Claude to
    tag and summarise; photos: queue each new page's photos for Claude to read."""
    store.migrate()
    done = Done(skipped=sum(not p.new for p in plan.pages))
    for page in plan.pages:
        if not page.new:
            continue
        blobs: dict[str, BlobRef] = {}
        for rel in page.images + page.files:
            if rel in blobs:
                continue
            with src.open(rel) as f:
                sha, size = store.put_blob(f)
            if sha != plan.sha[rel]:  # the page's text names the planned bytes
                raise RefusedError(f"{rel} changed since it was read: import again")
            name = None if STORED.fullmatch(rel) else posixpath.basename(rel)
            mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
            blobs[rel] = (sha, mime, size, name)
        main = "photo" if page.images else "note"
        captures: list[tuple[str, str, str | None, list[BlobRef]]] = [
            (page.cid, main, page.text, [blobs[r] for r in page.images])
        ]
        if page.files:
            cid = ulid(page.cid + "#files")
            captures.append((cid, "file", None, [blobs[r] for r in page.files]))
        record: dict[str, Any] = {
            "id": page.id,
            "slug": page.slug,
            "title": page.title,
            "body": page.body,
            "kind": page.kind,
            "fields": page.fields,
            "tags": page.tags,
            "created_at": page.created_at,
            "updated_at": page.updated_at,
            "made_by": page.made_by,
        }
        if len(page.body.encode()) > MAX_PAGE:  # grew as its links were made
            plan.note("too large", page.path, f"over {MAX_PAGE:,} bytes")
            continue
        try:
            _, new, queued = store.import_page(
                record, captures, author, photos=photos, files=True, enrich=enrich
            )
        except InvalidError as e:  # its text grew past MAX_PAGE as links were made
            plan.note("not imported", page.path, str(e))
            continue
        if not new:  # made meanwhile
            done.skipped += 1
            continue
        done.new += 1
        done.enrich += queued
        done.photos += len(page.images) if photos else 0
        done.files += sum(file_kind(blobs[r][1]) is not None for r in page.files)
    return done


def summary(plan: Plan) -> dict[str, Any]:
    """The plan in numbers: pages by kind, new and here already, and the files."""
    new = [p for p in plan.pages if p.new]

    return {
        "pages": len(plan.pages),
        "new": len(new),
        "skipped": len(plan.pages) - len(new),
        "kinds": dict(Counter(p.kind for p in new)),
        # what enrich would read: a note, todo or read with no photo
        "text_pages": sum(p.kind in ENRICH_KINDS and not p.images for p in new),
        "photos": sum(len(p.images) for p in new),
        "files": len({r for p in new for r in p.files}),
        "tag": plan.tag,
    }


def report(plan: Plan, done: Done | None = None, details: bool = False) -> str:
    """What was (or would be) imported, and every kind of problem: counted, and with
    details each one."""
    s = summary(plan)
    each = ", ".join(f"{n} {k}" for k, n in sorted(s["kinds"].items()))
    if done is None:
        out = [f"{s['pages']} pages, {s['new']} new" + (f": {each}" if each else "")]
    else:
        out = [f"imported {done.new} pages" + (f" ({each})" if each else "")]
    skipped = s["skipped"] if done is None else done.skipped
    if skipped:
        out.append(f"{skipped} here already, not imported again (nothing overwritten)")
    out.append(
        f"{s['photos']} photos shown inline and {s['files']} other files;"
        f" every page tagged {plan.tag}"
    )
    if done is not None:
        out.append(
            f"queued for Claude: {done.enrich} pages to tag and summarise,"
            f" {done.photos} photos to read; {done.files} files read locally"
        )
    for what, items in sorted(plan.issues.items()):
        out.append(f"{what}: {len(items)}")
        if details:
            out += [f"  {item}" for item in items]
    return "\n".join(out)
