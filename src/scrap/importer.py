"""scrap import: a Thoth vault (Obsidian-style Markdown with YAML front matter).

Each content page becomes a scrap page with its kind, fields, tags and dates; links
between pages become ``[[slug|label]]`` links and the images its pages embed become
the page's photos, shown inline. raw/ and inbox/ are dropped, so are index, log and
SCHEMA pages, and anything else that is not a page. See docs/how-to/import-a-vault.md.
"""

import hashlib
import math
import mimetypes
import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml

from . import markdown
from .markdown import Link, wiki_parts
from .store import (
    CROCKFORD,
    DEFAULT_FIELDS,
    MAX_INT,
    MAX_PAGE,
    BlobRef,
    Store,
    lines,
    slug_base,
    upload_limit,
)

__all__ = ["plan", "run", "report", "Plan"]

KINDS = {  # Thoth type -> scrap kind
    "note": "note",
    "entity": "reference",
    "memory": "memory",
    "action": "todo",
    "media": "consume",
}
FOLDERS = {  # a page with no type: its folder's
    "notes": "note",
    "entities": "reference",
    "memories": "memory",
    "actions": "todo",
    "media": "consume",
}
DROPPED = {"raw", "inbox"}  # with every folder starting "." or "_"
NOT_PAGES = {"index.md", "log.md", "SCHEMA.md"}  # at the top
FIELDS = {  # front matter -> scrap field
    "status": "status",
    "due_date": "due",
    "due": "due",
    "priority": "priority",
    "snoozed_until": "snoozed_until",  # a todo's column, as scrap exports it
    "media_type": "media_type",
    "url": "source",
    "source_url": "source",
    "memory_date": "memory_date",
    "summary": "summary",
    "personal": "personal",
}
USED = {"title", "type", "created", "updated", "tags"}  # read, not fields
STATUS = {"todo": "open"}  # Thoth's word -> scrap's; the rest are the same
STATUSES = ("open", "in_progress", "done", "cancelled")
SUBTYPE = {
    "book": "read",
    "article": "read",
    "film": "watch",
    "tv": "watch",
    "video": "watch",
    "podcast": "listen",
    "music": "listen",
}
DRAWINGS = (".excalidraw", ".excalidraw.md")
# Shown inline (the preview endpoint reads these); other images are attached as files
PREVIEWABLE = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/heic",
    "image/heif",
}
MAX_VALUE, MAX_KEY, MAX_FIELDS = 200, 40, 32  # as a PWA edit of fields allows
MAX_ALIASES = 64  # YAML aliases per page: refuse an alias bomb (Thoth uses a few)


@dataclass
class Page:
    path: str  # in the vault
    text: str  # the file as it is: kept as the capture's text
    title: str
    kind: str
    fields: dict[str, Any]
    tags: list[str]
    created_at: str
    updated_at: str
    body: str = ""  # with links and images rewritten
    slug: str = ""
    cid: str = ""
    new: bool = True  # False: imported already
    images: list[str] = field(default_factory=list)  # vault paths, in order
    files: list[str] = field(default_factory=list)  # PDFs


@dataclass
class Plan:
    vault: Path
    pages: list[Page] = field(default_factory=list)
    issues: dict[str, list[str]] = field(default_factory=dict)  # what, ["path: detail"]
    sha: dict[str, str] = field(default_factory=dict)  # asset path -> SHA-256
    limit: int = 50 << 20  # largest file imported

    def note(self, what: str, path: str, detail: str = "") -> None:
        self.issues.setdefault(what, []).append(f"{path}: {detail}" if detail else path)


class _Loader(yaml.SafeLoader):
    """safe_load with a cap on aliases."""

    aliases = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            self.aliases += 1
            if self.aliases > MAX_ALIASES:
                raise yaml.YAMLError("too many aliases")
        return super().compose_node(parent, index)


def _stamp(value: Any) -> str | None:
    """An ISO 8601 UTC time from a YAML date or datetime (or a string of one); a date
    alone is noon UTC."""
    if isinstance(value, str):
        text = value.strip()
        try:  # a date alone (2024-03-02 or 20240302) has no time part
            alone = "T" not in text.upper() and " " not in text
            value = date.fromisoformat(text) if alone else datetime.fromisoformat(text)
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC).isoformat(timespec="milliseconds")
        return value.replace("+00:00", "Z")
    if isinstance(value, date):
        return f"{value.isoformat()}T12:00:00.000Z"  # noon: the same day everywhere
    return None


def _ulid(key: str) -> str:
    """A ULID fixed by key (its time is 0): a page's path gives its capture the same
    id on every run, so a second run skips it."""
    n = int.from_bytes(hashlib.sha256(key.encode()).digest()[:10])
    return "".join(CROCKFORD[(n >> shift) & 31] for shift in range(125, -1, -5))


def _front(text: str) -> tuple[dict[str, Any] | None, str, str]:
    """The front matter (None if there is none), the body, and why the front matter
    could not be read ("" if it could, or there is none)."""
    if text.startswith("---\n"):
        head, sep, body = ("\n" + text[4:] + "\n").partition("\n---\n")
        if sep:
            try:
                fm = yaml.load(head, _Loader) or {}  # _Loader is a SafeLoader
            except (yaml.YAMLError, ValueError) as e:  # ValueError: a bad date
                return None, text, str(e).splitlines()[0][:80]
            if isinstance(fm, dict):
                return fm, body.removesuffix("\n"), ""
    return None, text, ""


def _skipped_dir(part: str) -> bool:
    return part in DROPPED or part.startswith((".", "_"))


def _read(plan: Plan, rel: str, path: Path) -> Page | None:
    try:
        stat = path.stat()
        if stat.st_size > MAX_PAGE:  # as for a page saved through the API (#62)
            plan.note("too large", rel, f"{stat.st_size:,} bytes, over {MAX_PAGE:,}")
            return None
        text = lines(path.read_text(encoding="utf-8", errors="replace"))
        mtime = datetime.fromtimestamp(stat.st_mtime, UTC)
    except OSError as e:
        plan.note("unreadable", rel, e.strerror or type(e).__name__)
        return None
    fm, body, why = _front(text)
    if why:
        plan.note("bad front matter", rel, why)
    if fm is None:
        plan.note("no front matter", rel)
        fm = {}
    folder = rel.split("/")[0] if "/" in rel else ""
    thoth = fm.get("type")
    if thoth is not None and (not isinstance(thoth, str) or thoth not in KINDS):
        plan.note("skipped", rel, f"type {thoth if isinstance(thoth, str) else '?'}")
        return None
    kind = KINDS.get(thoth or "", FOLDERS.get(folder, "note"))
    heading = re.match(r"\s*# (.+)\n?", body)
    title = fm.get("title")  # a scalar: a list could be an alias bomb
    title = " ".join(str(title).split()) if isinstance(title, str | int | float) else ""
    title = title or (heading[1].strip() if heading else Path(rel).stem)
    if heading and heading[1].strip() == title:  # the page shows its title already
        body = body[heading.end() :]
    fields: dict[str, Any] = dict(DEFAULT_FIELDS.get(kind, {}))
    for key, value in fm.items():
        if key in USED or value is None:
            continue
        name = FIELDS.get(key)
        if isinstance(value, date):
            value = value.isoformat()
        if name is None or not isinstance(value, str | bool | int | float):
            plan.note("unmapped field", rel, key)
            continue
        if isinstance(value, float) and not math.isfinite(value) or (
            isinstance(value, int) and not isinstance(value, bool)
            and abs(value) > MAX_INT
        ):  # fmt: skip
            plan.note("field dropped", rel, f"{key}: number out of range")
            continue
        if isinstance(value, str):
            value = " ".join(value.split())
            if len(value) > MAX_VALUE:  # the whole of it stays in the capture's text
                plan.note("field cut", rel, f"{key}: {len(value)} characters")
                value = value[: MAX_VALUE - 1] + "…"
        if name in ("status", "priority", "media_type"):
            value = str(value).lower()
            value = STATUS.get(value, value)
        if name == "status" and value not in STATUSES:
            plan.note("unknown status", rel, str(value))
        if name == "source" and "source" in fields:  # the first of url and source_url
            continue
        if name not in fields and len(fields) >= MAX_FIELDS:
            plan.note("field dropped", rel, f"{key}: over {MAX_FIELDS} fields")
            continue
        fields[name] = value
    if kind == "consume" and fields.get("media_type") in SUBTYPE:
        fields["subtype"] = SUBTYPE[fields["media_type"]]
    tags: list[str] = []
    raw_tags = fm.get("tags") or []
    for tag in raw_tags if isinstance(raw_tags, list) else [raw_tags]:
        if not isinstance(tag, str | int) or isinstance(tag, bool):
            plan.note("tag dropped", rel, type(tag).__name__)
            continue
        new = " ".join(str(tag).split()).lstrip("#").lower()[:64].strip()
        if new != str(tag):
            plan.note("tag changed", rel, f"{tag!r} -> {new!r}")
        if new and new not in tags:
            tags.append(new)
    stamps = {}
    for key in ("created", "updated", "memory_date"):
        if fm.get(key) is not None:
            stamps[key] = _stamp(fm[key])
            if stamps[key] is None:
                plan.note("invalid date", rel, key)
    created = (
        stamps.get("created")
        or stamps.get("memory_date")
        or stamps.get("updated")
        or _stamp(mtime)
    )
    assert created
    updated = max(stamps.get("updated") or created, created)
    return Page(rel, text, title, kind, fields, tags, created, updated, body)


class _Linker:
    """Rewrites one page's links and embeds, and collects its images and PDFs."""

    def __init__(self, plan: Plan, files: dict[str, Path], pages: dict[str, Page]):
        self.plan, self.files, self.pages = plan, files, pages
        self.by_name: dict[str, list[str]] = {}
        self.by_slug: dict[str, Page] = {}
        self.by_path: dict[str, list[str]] = {}  # lower-cased path -> vault paths
        self.bad: set[str] = set()  # images and PDFs too large or unreadable
        for rel in sorted(files, key=lambda r: (r.count("/"), r)):
            self.by_name.setdefault(posixpath.basename(rel).lower(), []).append(rel)
            self.by_path.setdefault(rel.lower(), []).append(rel)
        for page in pages.values():
            for key in (Path(page.path).stem, page.title):
                self.by_slug.setdefault(slug_base(key), page)

    def find(self, src: str, target: str, wiki: bool) -> tuple[str | None, bool]:
        """The vault path a link names, and whether it was only found by its name."""
        if wiki and "/" in target:  # a path: from the top, else from here
            paths = [
                posixpath.normpath(posixpath.join(base, target.lstrip("/")))
                for base in ("", posixpath.dirname(src))
            ]
            for path in paths:  # exact case first
                for rel in (path, path + ".md"):
                    if rel in self.files:
                        return rel, False
            for path in paths:  # then any case
                low = path.lower()
                got = self.by_path.get(low) or self.by_path.get(low + ".md") or []
                if got:
                    if len(got) > 1:
                        self.plan.note("ambiguous link", src, f"{target} -> {got[0]}")
                    return got[0], False
        if wiki:  # Obsidian: by name, wherever it is
            name = posixpath.basename(target).lower()
            got = self.by_name.get(name) or self.by_name.get(name + ".md") or []
            here = posixpath.dirname(src)
            # imported pages first, then the linking page's folder, then any but
            # dropped ones, nearest the top first
            got = sorted(
                got,
                key=lambda r: (
                    r not in self.pages,
                    posixpath.dirname(r) != here,
                    _skipped_dir(r.split("/")[0]) if "/" in r else False,
                    r.count("/"),
                    r,
                ),
            )
            if len(got) > 1:
                self.plan.note("ambiguous link", src, f"{target} -> {got[0]}")
            return (got[0] if got else None), False
        for base in (posixpath.dirname(src), ""):
            rel = posixpath.normpath(posixpath.join(base, target))
            if rel in self.files:
                return rel, False
        if target.endswith(".md"):  # a renamed page, maybe: by its file name or title
            page = self.by_slug.get(slug_base(posixpath.basename(target)[:-3]))
            if page:
                return page.path, True
        return None, False

    def asset(self, page: Page, rel: str) -> str | None:
        """Attach an image or PDF to the page; its SHA-256, or None if it is neither,
        or cannot be read (reported)."""
        mime = mimetypes.guess_type(rel)[0] or ""
        if not (mime.startswith("image/") or mime == "application/pdf"):
            return None
        if rel in self.bad:
            return None
        if rel not in self.plan.sha:
            self.bad.add(rel)  # until it is read
            try:
                if self.files[rel].stat().st_size > self.plan.limit:
                    self.plan.note("too large", rel, f"over {self.plan.limit >> 20} MB")
                    return None
                with open(self.files[rel], "rb") as f:
                    sha = hashlib.file_digest(f, "sha256").hexdigest()
            except OSError as e:
                self.plan.note("unreadable", rel, e.strerror or type(e).__name__)
                return None
            self.plan.sha[rel] = sha
            self.bad.discard(rel)
        attached = page.images if mime in PREVIEWABLE else page.files
        if rel not in attached:
            attached.append(rel)
        return self.plan.sha[rel]

    def token(self, page: Page, link: Link) -> str | None:
        """What replaces a link, image or wiki link (None: kept as it is). In a table
        cell every pipe is escaped: a bare one would end the cell."""
        new = self._token(page, link)
        if new is None or not link.in_table:
            return new
        return new.replace("\\|", "|").replace("|", "\\|")

    def _token(self, page: Page, link: Link) -> str | None:
        wiki = link.kind == "wiki"
        embed = link.embed
        if wiki:
            target, label = wiki_parts(link.target)
            target = target.split("#")[0].strip()
        else:
            target, label = link.target, link.label
            if re.match(r"[a-z][a-z0-9+.-]*:", target, re.I):  # http(s), mailto: as is
                return None
            target = unquote(target.split("#")[0])
        name = posixpath.basename(target) or target
        if not target:  # #anchor: within the page
            return label or (link.target if wiki else "").lstrip("#").strip()
        rel, by_name = self.find(page.path, target, wiki)
        if rel is None:
            what = "missing file" if embed else "broken link"
            self.plan.note(what, page.path, target)
            return label or name
        if by_name:
            self.plan.note("link found by name", page.path, target)
        if rel in self.pages:
            linked = self.pages[rel]
            # A bracket in a title would end or confuse the link: use a parenthesis
            label = label or linked.title.replace("[", "(").replace("]", ")")
            if label == linked.slug:
                return f"[[{label}]]"
            return f"[[{linked.slug}|{label}]]"
        if rel.endswith(".md") and not rel.endswith(DRAWINGS):
            self.plan.note("link to dropped page", page.path, rel)
            return label or name
        sha = self.asset(page, rel)
        if sha is None:
            if rel not in self.bad:
                self.plan.note("file not imported", page.path, rel)
            return f"*{name} (not imported)*"
        if embed and rel in page.images:
            return f"![{label}](/api/blobs/{sha}/preview?size=2048)"
        return f"*{label or name} (attached)*"

    def rewrite(self, page: Page) -> str:
        """The page's text with its links, images and wiki links rewritten (as
        Markdown parses it: never in code)."""

        def unmapped(line: int) -> None:
            self.plan.note("links kept as typed", page.path, f"body line {line}")

        return markdown.rewrite(
            page.body, lambda link: self.token(page, link), unmapped
        ).strip("\n")


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
