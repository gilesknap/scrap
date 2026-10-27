"""The vault import's tables of names and limits, and its Page and Plan."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KINDS = {  # Thoth type -> scrap kind
    "note": "note",
    "entity": "document",
    "memory": "document",
    "action": "todo",
    "media": "consume",
}
FOLDERS = {  # a page with no type: its folder's
    "notes": "note",
    "entities": "document",
    "memories": "document",
    "actions": "todo",
    "media": "consume",
}
KIND_TAGS = {"entity": "entity", "memory": "memory"}  # Thoth type -> the tag it keeps
FOLDER_TAGS = {"entities": "entity", "memories": "memory"}  # a page with no type
DROPPED = {"raw", "inbox"}  # with every folder starting "." or "_"
NOT_PAGES = {"index.md", "log.md", "SCHEMA.md"}  # at the top
FIELDS = {  # front matter -> scrap field
    "status": "status",
    "due_date": "due",
    "due": "due",
    "priority": "priority",
    "snoozed_until": "snoozed_until",  # a todo's value, as scrap exports it
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
