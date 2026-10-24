"""Planning an import from a vault, running it and reporting on it."""

import mimetypes
import posixpath
from collections import Counter
from pathlib import Path

from ..store import BlobRef, Store, slug_base, upload_limit
from .linker import _Linker
from .model import DRAWINGS, NOT_PAGES, Page, Plan
from .reading import _read, _skipped_dir, _ulid


def plan(vault: Path, store: Store) -> Plan:
    """Read the vault and work out every page, its slug and its rewritten body.
    Writes nothing; slugs already in store are avoided."""
    result = Plan(vault, limit=upload_limit())
    root = vault.resolve()
    files: dict[str, Path] = {}
    for path in sorted(vault.rglob("*")):
        rel = path.relative_to(vault).as_posix()
        if any(p.startswith(".") for p in rel.split("/")):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            result.note("symlink skipped", rel)  # never read outside the vault
        elif path.is_file():
            files[rel] = path
    pages: dict[str, Page] = {}
    dropped: Counter[str] = Counter()
    for rel, path in files.items():
        parts = rel.split("/")
        if len(parts) > 1 and _skipped_dir(parts[0]):
            dropped[parts[0]] += 1
            continue
        if not rel.endswith(".md") or rel.endswith(DRAWINGS):
            result.note("skipped", rel, "not a page")
        elif len(parts) == 1 and rel in NOT_PAGES:
            result.note("skipped", rel, "index, log or schema")
        elif page := _read(result, rel, path):
            pages[rel] = page
    for folder, n in sorted(dropped.items()):
        result.note("dropped folder", f"{folder}/", f"{n} files")
    # Slugs: from the file name, in path order; a page imported before keeps its own
    for page in pages.values():
        page.cid = _ulid(page.path)
    done = store.imported([p.cid for p in pages.values()])
    taken = store.slugs() - set(done.values())
    for page in pages.values():
        if page.cid in done:
            page.slug, page.new = done[page.cid], False
            taken.add(page.slug)
    for page in pages.values():
        if page.new:
            base = slug_base(Path(page.path).stem)
            slug, n = base, 1
            while slug in taken:
                n += 1
                slug = f"{base}-{n}"
            if slug != base:
                result.note("slug collision", page.path, slug)
            page.slug = slug
            taken.add(slug)
    linker = _Linker(result, files, pages)
    for page in pages.values():
        page.body = linker.rewrite(page)
    used = {rel for page in pages.values() for rel in page.images + page.files}
    for rel in files:
        mime = mimetypes.guess_type(rel)[0] or ""
        if rel.startswith("raw/") and mime.startswith("image/") and rel not in used:
            result.note("unreferenced image", rel)
    result.pages = list(pages.values())
    return result


def run(store: Store, plan: Plan, ingest: bool = False, author: str = "import") -> int:
    """Import the planned pages that are not there yet; return how many."""
    store.migrate()
    root = plan.vault.resolve()
    count = 0
    for page in plan.pages:
        if not page.new:
            continue
        blobs: dict[str, BlobRef] = {}
        for rel in page.images + page.files:
            path = plan.vault / rel  # checked again: it may have changed since plan()
            changed = SystemExit(f"{rel} changed since it was checked: run again")
            try:
                if (
                    path.is_symlink()
                    or not path.resolve().is_relative_to(root)
                    or path.stat().st_size > plan.limit
                ):
                    raise changed
                with open(path, "rb") as f:
                    sha, size = store.put_blob(f)
            except OSError:
                raise changed from None
            if sha != plan.sha[rel]:  # the page's text names the planned bytes
                raise changed
            mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
            blobs[rel] = (sha, mime, size, posixpath.basename(rel))
        main = "photo" if page.images else "note"
        captures: list[tuple[str, str, str | None, list[BlobRef]]] = [
            (page.cid, main, page.text, [blobs[r] for r in page.images])
        ]
        if page.files:
            cid = _ulid(page.path + "#files")
            captures.append((cid, "file", None, [blobs[r] for r in page.files]))
        record = {
            "slug": page.slug,
            "title": page.title,
            "body": page.body,
            "kind": page.kind,
            "fields": page.fields,
            "tags": page.tags,
            "created_at": page.created_at,
            "updated_at": page.updated_at,
        }
        count += store.import_page(record, captures, author, enqueue=ingest)[1]
    return count


def report(plan: Plan, details: bool) -> str:
    """Counts of pages by kind and of every kind of issue, and with details each one."""
    kinds = Counter(p.kind for p in plan.pages)
    folders = Counter(
        p.path.split("/")[0] if "/" in p.path else "." for p in plan.pages
    )
    new = sum(p.new for p in plan.pages)
    images = len({r for p in plan.pages for r in p.images})
    files = len({r for p in plan.pages for r in p.files})
    each = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
    out = [
        f"{len(plan.pages)} pages ({new} new)" + (f": {each}" if each else ""),
        "by folder: " + ", ".join(f"{k}/ {n}" for k, n in sorted(folders.items())),
        f"{images} images shown inline and {files} other files attached;"
        f" {sum(len(p.tags) for p in plan.pages)} tags",
    ]
    for what, items in sorted(plan.issues.items()):
        out.append(f"{what}: {len(items)}")
        if details:
            out += [f"  {item}" for item in items]
    return "\n".join(out)
