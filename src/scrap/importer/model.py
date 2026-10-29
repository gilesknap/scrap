"""The import's names and limits, and its Page and Plan."""

import re
from dataclasses import dataclass, field
from typing import Any

from ..store import KINDS

__all__ = ["KINDS", "Page", "Plan"]

# Front matter keys read as the page's own, not fields (export.OWN, and the date and
# kind names other tools use)
OWN = {
    "title", "aliases", "id", "kind", "tags", "created", "updated", "due",
    "priority", "made_by", "attachments", "fields",
}  # fmt: skip
CREATED = ("created", "created_at", "date")  # the first given is the page's
UPDATED = ("updated", "updated_at", "modified")
DATES = {*CREATED, *UPDATED}
DRAWINGS = (".excalidraw", ".excalidraw.md")
# A file of a scrap export's files/ folder: named by its SHA-256 (a drawing adds the
# capture's id), never a page even if it is Markdown (fullmatch)
STORED = re.compile(
    r"(?:[^/]+/)*files/[0-9a-f]{64}(?:-[0-9A-Z]{26})?(?:\.[A-Za-z0-9]+)*"
)
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
MAX_VALUE, MAX_FIELDS = 200, 32  # as a PWA edit of fields allows
MAX_ALIASES = 64  # YAML aliases per page: refuse an alias bomb
MAX_ENTRIES = 100_000  # files in an archive or folder
MAX_TOTAL = 64 << 30  # bytes, all files read: a zip bomb stops here


@dataclass
class Page:
    path: str  # in the archive
    text: str  # the file as it is: kept as the capture's text
    title: str
    kind: str
    fields: dict[str, Any]
    tags: list[str]
    created_at: str
    updated_at: str
    body: str = ""  # with links and images rewritten
    id: str | None = None  # the front matter's, if a ULID: the page's id
    made_by: str = "human"
    slug: str = ""
    cid: str = ""
    new: bool = True  # False: here already (by id or by path and content)
    why: str = ""  # if not new
    images: list[str] = field(default_factory=list)  # archive paths, in order
    files: list[str] = field(default_factory=list)  # other files
    attachments: list[str] = field(default_factory=list)  # the front matter's


@dataclass
class Plan:
    pages: list[Page] = field(default_factory=list)
    issues: dict[str, list[str]] = field(default_factory=dict)  # what, ["path: detail"]
    sha: dict[str, str] = field(default_factory=dict)  # asset path -> SHA-256
    limit: int = 50 << 20  # largest file imported
    tag: str = ""  # import/<date>, given to every page

    def note(self, what: str, path: str, detail: str = "") -> None:
        self.issues.setdefault(what, []).append(f"{path}: {detail}" if detail else path)
