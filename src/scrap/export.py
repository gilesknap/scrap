"""The whole store as Markdown (#417), a folder (`scrap export DIR`) or a zip streamed
from GET /api/store/download, laid out so it opens as an Obsidian vault:

- `<slug>.md` per page not in the trash: YAML front matter with the owner's data only
  (title, aliases, id, kind, tags, created, updated, a todo's due and priority, each
  field, made_by when not human, and attachments: the files the text does not embed),
  then the body exactly as stored, its files' addresses made `files/<name>`. Its
  `[[slug]]` links name the files here, so they resolve with no rewriting.
- `files/` the originals, named by content (`<sha256>.<ext>`), and the drawings.
- `_claude/<slug>.md` what a model wrote about the page (its summary, the tags it added,
  a write-up or topic synthesis, related pages, and each photo's description, the
  text read from it and its drawing). Model text never goes in `<slug>.md`: a file
  read back in would make it the owner's (ADR 0020, 0027).

The pages are read in one transaction; the files are copied (or streamed) after it. The
trash, revisions and model runs are left out: backup is the full-fidelity copy.
"""

import json
import os
import re
import shutil
import sqlite3
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .backup import _derived, _drawing_name, _fenced, _sha_name, localise
from .drawing import excalidraw_file
from .markdown import rewrite, wiki_link
from .page_notes import NOTES_HEADING, Extras, _notes, _quoted
from .store import Store
from .store.todo import read as read_todo

__all__ = ["SIDECAR", "export", "stream", "pages"]

SIDECAR = "_claude"  # model text, beside the pages; an import skips it
BANNER = (
    "*Written by a model, may be wrong. Not part of the page: "
    "an import never reads this folder.*"
)
# Front matter keys of scrap's own; a field of the same name goes under fields:
OWN = (
    "title", "aliases", "id", "kind", "tags", "created", "updated", "due",
    "priority", "made_by", "attachments", "fields",
)  # fmt: skip
# What YAML may not hold as it is (C1 controls, its line breaks, non-characters)
NOT_YAML = re.compile(r"[\x7f-\x9f\u2028\u2029\ufeff\ufffe\uffff]")
PLAIN_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
# Bare, YAML 1.1 reads these as a boolean or null, not a name
YAML_WORDS = {"y", "n", "yes", "no", "on", "off", "true", "false", "null"}
CHUNK = 1 << 20  # bytes of a file read and sent at a time


def _yaml(value: Any) -> str:
    """value as YAML: JSON (a YAML subset), the characters YAML refuses escaped."""
    text = json.dumps(value, ensure_ascii=False)
    return NOT_YAML.sub(lambda m: f"\\u{ord(m[0]):04x}", text)


@dataclass
class Page:
    """One page's part of an export."""

    slug: str
    text: str  # <slug>.md
    notes: str | None  # _claude/<slug>.md, if a model wrote anything about it
    files: list[tuple[str, str | bytes]] = field(default_factory=list)


def _front(
    conn: sqlite3.Connection, row: sqlite3.Row, p: dict[str, Any], attachments: list
) -> list[str]:
    tags = [t for t in p["tags"] if t not in p["model_tags"]]  # the owner's
    front: dict[str, Any] = {
        "title": row["title"],
        "aliases": [row["title"]],
        "id": row["id"],
        "kind": row["kind"],
    }
    if tags:
        front["tags"] = tags
    lines = [f"{k}: {_yaml(v)}" for k, v in front.items()]
    # Unquoted, so Obsidian shows them as dates (ISO 8601 UTC)
    lines += [f"created: {row['created_at']}", f"updated: {row['updated_at']}"]
    rest: dict[str, Any] = {}
    if row["kind"] == "todo":
        rest |= {k: v for k, v in read_todo(conn, row["id"]).items() if v}
    fields = json.loads(row["fields"])
    rest |= {k: v for k, v in fields.items() if k not in OWN}
    if p["made_by"] != "human":
        rest["made_by"] = p["made_by"]
    if attachments:
        rest["attachments"] = attachments
    if clash := {k: v for k, v in fields.items() if k in OWN}:
        rest["fields"] = clash
    return ["---", *lines, *(f"{_key(k)}: {_yaml(v)}" for k, v in rest.items()), "---"]


def _key(name: str) -> str:
    """A front matter key: bare if it is a plain name, else quoted (a field's name is
    free text, and `a: b` or `# x` bare would be other YAML)."""
    plain = PLAIN_KEY.fullmatch(name) and name.lower() not in YAML_WORDS
    return name if plain else _yaml(name)


def _here(slug: str) -> str:
    """A page's file as a link from _claude/: a relative path, since a [[slug]] there
    would find _claude/<slug>.md, its own folder's file of that name."""
    return f"../{quote(slug)}.md"


def _sidecar_links(text: str) -> str:
    return rewrite(text, lambda link: wiki_link(link, _here))


def _page(store: Store, conn: sqlite3.Connection, row: sqlite3.Row) -> Page:
    local = localise(conn, row, _sha_name, verbatim=True)
    p = store.page_in(conn, row["id"])
    gone = set(p["removed"])  # files whose embeds the owner deleted: not shown
    attachments, photos = [], []
    seen: set[str] = set()
    for blob in local.blobs:
        sha = blob["sha256"]
        if sha in seen or sha in gone:
            continue
        seen.add(sha)
        if sha not in local.linked:
            attachments.append(f"[[files/{local.names[sha]}]]")
        if blob["mime"].startswith("image/"):
            photos.append(blob)
    keep = {local.names[s] for s in seen} | {
        n for n, c in local.files if isinstance(c, str) and c in local.linked
    }
    files = [(n, c) for n, c in local.files if n in keep]
    front = _front(conn, row, p, attachments)
    text = "\n".join([*front, "", local.body, ""])
    notes = _notes(p, Extras())  # Extras(): [[slug]] links as they are
    for blob in photos:
        notes += _photo(conn, blob, local.names[blob["sha256"]], local.taken, files)
    if not notes:
        return Page(row["slug"], text, None, files)
    if notes[0] != NOTES_HEADING:  # photos only
        notes.insert(0, NOTES_HEADING)
    slug, title = row["slug"], row["title"].replace("[", "(").replace("]", ")")
    head = ["---", f"generated_by: {_yaml('claude')}", f"page: {_yaml(slug)}", "---"]
    about = [BANNER, "", f"About [{title or slug}]({_here(slug)}).", ""]
    sidecar = _sidecar_links("\n".join([*head, "", *about, *notes]))
    return Page(slug, text, sidecar.rstrip("\n") + "\n", files)


def _photo(
    conn: sqlite3.Connection,
    blob: sqlite3.Row,
    file: str,
    taken: set[str],
    files: list[tuple[str, str | bytes]],
) -> list[str]:
    """What a model made of a photo: its description, the text it read and the
    drawing (added to files), as lines of the sidecar; none if nothing."""
    got = _derived(conn, blob["capture_id"], blob["sha256"])
    label = (blob["filename"] or file).replace("[", "(").replace("]", ")")
    lines: list[str] = []
    if "description" in got and got["description"]["text"]:
        lines += ["", *_quoted(got["description"]["text"])]
    if "ocr" in got and got["ocr"]["text"]:
        lines += ["", *_fenced(got["ocr"]["text"])]
    if "excalidraw" in got:
        # One files/ folder for every page: a photo is the same file on each page
        # that has it, but its drawing is per capture
        drawing = _drawing_name(f"{blob['sha256']}-{blob['capture_id']}", taken)
        taken.add(drawing)
        files.append((drawing, excalidraw_file(json.loads(got["excalidraw"]["data"]))))
        lines += ["", f"[Drawing of {label}](../files/{quote(drawing)})"]
    if not lines:
        return []
    return ["", f"### Photo [{label}](../files/{quote(file)})", *lines]


def pages(store: Store) -> Iterator[Page]:
    """Each page not in the trash, oldest first, as its export has it; read in one
    transaction (a consistent copy while scrap is serving)."""
    if not store.db.is_file():
        raise SystemExit(f"no database at {store.db}")
    with store.connect() as conn:
        conn.execute("BEGIN")  # a read: one snapshot for every page
        try:
            rows = conn.execute(
                "SELECT * FROM page WHERE deleted_at IS NULL ORDER BY created_at, id"
            ).fetchall()
            for row in rows:
                yield _page(store, conn, row)
        finally:
            conn.execute("ROLLBACK")


def _entries(store: Store) -> tuple[list[tuple[str, str | bytes | Path]], int]:
    """Every file of an export, by its path in it, with its text, bytes or the stored
    file to copy (each stored file once); and how many pages."""
    out: list[tuple[str, str | bytes | Path]] = []
    done: set[str] = set()
    count = 0
    for page in pages(store):
        count += 1
        out.append((f"{page.slug}.md", page.text))
        if page.notes:
            out.append((f"{SIDECAR}/{page.slug}.md", page.notes))
        for name, content in page.files:
            if name in done:
                continue
            done.add(name)
            path = store.blob_path(content) if isinstance(content, str) else content
            out.append((f"files/{name}", path))
    return out, count


def export(store: Store, dest: Path) -> int:
    """Write the export into the folder dest; return how many pages."""
    entries, count = _entries(store)
    (dest / "files").mkdir(parents=True, exist_ok=True)
    for name, content in entries:
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        elif isinstance(content, bytes):
            target.write_bytes(content)
        elif not target.exists():  # by content: one there is the same
            try:
                shutil.copyfile(content, target)
            except FileNotFoundError:  # gone since the pages were read (scrap gc)
                target.unlink(missing_ok=True)
    return count


class _Sink:
    """An unseekable file the zip is written to, emptied as it is sent."""

    def __init__(self) -> None:
        self.held = bytearray()
        self.at = 0

    def write(self, data: bytes) -> int:
        self.held += data
        self.at += len(data)
        return len(data)

    def tell(self) -> int:
        return self.at

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        data = bytes(self.held)
        self.held.clear()
        return data


def _info(name: str, st: os.stat_result) -> zipfile.ZipInfo:
    """A stored file's zip entry, from the open file (not its path, which may go)."""
    info = zipfile.ZipInfo(name, time.localtime(st.st_mtime)[:6])
    info.file_size = st.st_size  # so a file over 4 GB gets ZIP64 headers
    info.external_attr = (st.st_mode & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_STORED  # photos are compressed already
    return info


def stream(store: Store) -> Iterator[bytes]:
    """The export as a zip, a chunk at a time: never all in memory, nor on disk.

    The pages' text is made first (one transaction; the drawings are made in memory
    too); then each stored file is read and sent CHUNK bytes at a time. Photos are
    compressed already, so files are stored as they are; the Markdown is deflated."""
    entries, _ = _entries(store)
    sink = _Sink()
    with zipfile.ZipFile(sink, "w") as zf:  # type: ignore[arg-type]
        for name, content in entries:
            if isinstance(content, str | bytes):
                data = content.encode() if isinstance(content, str) else content
                zf.writestr(name, data, zipfile.ZIP_DEFLATED)
            else:
                try:
                    src = content.open("rb")
                except FileNotFoundError:  # gone since the pages were read: left out
                    continue
                with src, zf.open(_info(name, os.fstat(src.fileno())), "w") as dst:
                    while chunk := src.read(CHUNK):
                        dst.write(chunk)
                        yield sink.take()
            yield sink.take()
    yield sink.take()
