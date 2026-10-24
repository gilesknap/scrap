"""Rewriting a page's links and embeds, and collecting its images and PDFs."""

import hashlib
import mimetypes
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote

from .. import markdown
from ..markdown import Link, wiki_parts
from ..store import slug_base
from .model import DRAWINGS, PREVIEWABLE, Page, Plan
from .reading import _skipped_dir


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
