"""Rewriting a page's links and embeds, and collecting its images and files.

A link to another imported page becomes `[[slug|label]]`, unless it names that page's
slug already (as every link in a scrap export does): then it is kept byte for byte. A
link or embed of a file in the archive becomes the stored file's address, an image
shown inline at `/api/blobs/<sha>/preview?size=2048`, any other file linked at
`/api/blobs/<sha>`. A link to nothing in the archive is kept as typed (and reported),
so the text is never lost."""

import hashlib
import mimetypes
import posixpath
import re
from urllib.parse import unquote

from .. import markdown
from ..markdown import Link, wiki_parts
from ..store import slug_base
from .model import DRAWINGS, PREVIEWABLE, STORED, Page, Plan
from .sources import Source

SIZE = re.compile(r"\d+(?:x\d+)?")  # Obsidian's ![[image.png|300]]: a width, no alt


def is_page(rel: str) -> bool:
    """Whether an archive file is a page: Markdown, not a drawing nor a stored file."""
    return (
        rel.endswith(".md") and not rel.endswith(DRAWINGS) and not STORED.fullmatch(rel)
    )


class Linker:
    """Rewrites one page's links and embeds, and collects its images and files."""

    def __init__(self, plan: Plan, src: Source, pages: dict[str, Page]):
        self.plan, self.src, self.pages = plan, src, pages
        self.by_name: dict[str, list[str]] = {}
        self.by_slug: dict[str, Page] = {}
        self.by_path: dict[str, list[str]] = {}  # lower-cased path -> archive paths
        self.bad: set[str] = set()  # files too large or unreadable
        for rel in sorted(src.files, key=lambda r: (r.count("/"), r)):
            self.by_name.setdefault(posixpath.basename(rel).lower(), []).append(rel)
            self.by_path.setdefault(rel.lower(), []).append(rel)
        for page in pages.values():
            for key in (
                posixpath.splitext(posixpath.basename(page.path))[0],
                page.title,
            ):
                self.by_slug.setdefault(slug_base(key), page)

    def find(self, src: str, target: str, wiki: bool) -> tuple[str | None, bool]:
        """The archive path a link names, and whether it was only found by its name."""
        files = self.src.files
        if wiki and "/" in target:  # a path: from the top, else from here
            paths = [
                posixpath.normpath(posixpath.join(base, target.lstrip("/")))
                for base in ("", posixpath.dirname(src))
            ]
            for path in paths:  # exact case first
                for rel in (path, path + ".md"):
                    if rel in files:
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
            # pages first, then the linking page's folder, nearest the top first
            got = sorted(
                got,
                key=lambda r: (
                    r not in self.pages,
                    posixpath.dirname(r) != here,
                    r.count("/"),
                    r,
                ),
            )
            if len(got) > 1:
                self.plan.note("ambiguous link", src, f"{target} -> {got[0]}")
            return (got[0] if got else None), False
        for base in (posixpath.dirname(src), ""):
            rel = posixpath.normpath(posixpath.join(base, target))
            if rel in files:
                return rel, False
        if target.endswith(".md"):  # a renamed page, maybe: by its file name or title
            page = self.by_slug.get(slug_base(posixpath.basename(target)[:-3]))
            if page:
                return page.path, True
        return None, False

    def asset(self, page: Page, rel: str) -> str | None:
        """Attach a file to the page; its SHA-256, or None if it cannot be read
        (reported)."""
        if rel in self.bad:
            return None
        if rel not in self.plan.sha:
            self.bad.add(rel)  # until it is read
            if self.src.files[rel].size > self.plan.limit:
                self.plan.note("too large", rel, f"over {self.plan.limit >> 20} MB")
                return None
            try:
                digest = hashlib.sha256()
                with self.src.open(rel) as f:
                    while chunk := f.read(1 << 20):
                        digest.update(chunk)
                sha = digest.hexdigest()
            except Exception as e:  # OSError, a bad zip entry (BadZipFile, zlib)
                self.plan.note("unreadable", rel, str(e)[:80] or type(e).__name__)
                return None
            self.plan.sha[rel] = sha
            self.bad.discard(rel)
        attached = page.images if mime(rel) in PREVIEWABLE else page.files
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
            typed, label = wiki_parts(link.target)
            target = typed.split("#")[0].strip()
        else:
            target, label = link.target, link.label
            if re.match(r"[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("/"):
                return None  # http(s), mailto:, a path on the server: as it is
            target = unquote(target.split("#")[0])
        if not target:  # #anchor: within the page
            return None
        rel, by_name = self.find(page.path, target, wiki)
        if rel is None:
            self.plan.note(
                "missing file" if embed else "broken link", page.path, target
            )
            return None
        if by_name:
            self.plan.note("link found by name", page.path, target)
        if rel in self.pages:
            linked = self.pages[rel]
            if wiki and not embed and target == linked.slug:
                return None  # names the page already: kept byte for byte
            # A bracket in a title would end or confuse the link: use a parenthesis
            label = label or linked.title.replace("[", "(").replace("]", ")")
            if label == linked.slug:
                return f"[[{label}]]"
            return f"[[{linked.slug}|{label}]]"
        if is_page(rel) or rel.endswith(DRAWINGS):
            self.plan.note("link to a page not imported", page.path, rel)
            return None
        sha = self.asset(page, rel)
        if sha is None:
            return None
        if embed and mime(rel).startswith("image/"):
            alt = "" if wiki and SIZE.fullmatch(label) else label
            if rel in page.images:
                return f"![{alt}](/api/blobs/{sha}/preview?size=2048)"
            return f"![{alt}](/api/blobs/{sha})"  # an image not previewed (SVG)
        # A link (an embedded PDF too): its text as typed; else the file's name, but
        # for a scrap export's file, named by its SHA-256
        text = label or ("" if STORED.fullmatch(rel) else posixpath.basename(rel))
        return f"[{text.replace('[', '(').replace(']', ')')}](/api/blobs/{sha})"

    def rewrite(self, page: Page) -> str:
        """The page's text with its links, images and wiki links rewritten (as
        Markdown parses it: never in code)."""

        def unmapped(line: int) -> None:
            self.plan.note("links kept as typed", page.path, f"body line {line}")

        return markdown.rewrite(
            page.body, lambda link: self.token(page, link), unmapped
        )

    def attach(self, page: Page) -> None:
        """The files the front matter's attachments name (`[[files/x.pdf]]`), added
        to the page but not to its text."""
        for item in page.attachments:
            target = item.strip()
            if target.startswith("[[") and target.endswith("]]"):
                target = wiki_parts(target[2:-2])[0]
            rel = self.find(page.path, target, True)[0] if target else None
            if rel is None or is_page(rel):
                self.plan.note("missing file", page.path, target or "attachments")
            else:
                self.asset(page, rel)


def mime(rel: str) -> str:
    return mimetypes.guess_type(rel)[0] or "application/octet-stream"
