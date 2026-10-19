"""Backup, restore and Markdown export of a data folder."""

import json
import mimetypes
import re
import shutil
import sqlite3
import zipfile
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import IO
from urllib.parse import quote

from .drawing import excalidraw_file
from .store import NotFoundError, Store, connect, migrate, schema_version

__all__ = ["backup", "restore", "export", "page_markdown", "download", "file_name"]

Namer = Callable[[sqlite3.Row, set[str]], str]


def _copy_files(src: Path, dest: Path) -> None:
    # Blobs are content-addressed: a file already there holds the same bytes.
    for path in src.rglob("*"):
        target = dest / path.relative_to(src)
        if path.is_file() and not path.name.startswith(".") and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _snapshot(src: Path, dest: Path) -> None:
    """Copy a live database consistently with the SQLite online backup API."""
    part = dest.with_name(dest.name + ".part")
    part.unlink(missing_ok=True)
    source, target = connect(src), sqlite3.connect(part)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    part.replace(dest)


def backup(store: Store, dest: Path) -> None:
    """Snapshot the database, then copy files/; safe while scrap is serving.

    Blobs are written before the transaction that records them, so every blob the
    snapshot names is already in files/ when the copy starts.
    """
    if not store.db.is_file():
        raise SystemExit(f"no database at {store.db}")
    dest.mkdir(parents=True, exist_ok=True)
    _snapshot(store.db, dest / "scrap.db")
    _copy_files(store.files, dest / "files")


def restore(src: Path, store: Store, force: bool = False) -> None:
    """Restore a backup into a data folder that is empty (or any, with force).

    The backup's database is copied beside the live one first, and only the copy
    is opened: the backup itself may be on read-only media (a WAL database cannot
    be opened in a read-only directory). The copy is checked and migrated, then
    swapped in at the end. Files are only ever added. A refused backup leaves the
    data folder as it was.
    """
    backup_db = src / "scrap.db"
    if not backup_db.is_file():
        raise SystemExit(f"no backup at {src}")
    used = store.db.exists() or (store.files.is_dir() and any(store.files.iterdir()))
    if used and not force:
        raise SystemExit(f"{store.dir} is not empty; stop scrap and use --force")
    created = not store.dir.exists()
    store.dir.mkdir(parents=True, exist_ok=True)
    part = store.dir / "scrap.db.restore"
    try:
        _discard(part)
        shutil.copyfile(backup_db, part)
        # A backup is a closed snapshot with no -wal; copy one if it is there
        if Path(f"{backup_db}-wal").is_file():
            shutil.copyfile(f"{backup_db}-wal", f"{part}-wal")
        schema_version(part)  # refuses a backup newer than this scrap
        with closing(connect(part)) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise sqlite3.DatabaseError(f"integrity_check says {check}")
    except (RuntimeError, sqlite3.DatabaseError, OSError) as error:
        _discard(part)
        if created:
            store.dir.rmdir()
        what = "cannot copy the backup" if isinstance(error, OSError) else "bad backup"
        raise SystemExit(f"{what}: {error}") from None
    store.files.mkdir(parents=True, exist_ok=True)
    _copy_files(src / "files", store.files)
    migrate(part)
    Path(f"{part}.lock").unlink()
    for suffix in ("-wal", "-shm"):
        Path(f"{store.db}{suffix}").unlink(missing_ok=True)
    part.replace(store.db)


def _discard(db: Path) -> None:
    for suffix in ("", "-wal", "-shm", ".lock"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)


def _sha_name(blob: sqlite3.Row, taken: set[str]) -> str:
    return blob["sha256"] + (mimetypes.guess_extension(blob["mime"]) or "")


def _derived(conn: sqlite3.Connection, cid: str, sha: str) -> dict[str, sqlite3.Row]:
    """A photo's current results (text, description, drawing) by kind."""
    return {
        row["kind"]: row
        for row in conn.execute(
            "SELECT kind, text, data FROM derived WHERE capture_id = ?"
            " AND source_sha256 = ? AND superseded_at IS NULL",
            (cid, sha),
        )
    }


def _fenced(text: str) -> list[str]:
    fence = "```"
    while fence in text:
        fence += "`"
    return [f"{fence}text", text, fence]


def page_markdown(
    conn: sqlite3.Connection, page: sqlite3.Row, name: Namer = _sha_name
) -> tuple[str, list[tuple[str, str | bytes]]]:
    """A page as Markdown: front matter, its body, then a link per file under files/,
    each photo followed by what Claude made of it (its description, the text it read
    and the drawing, as an .excalidraw file beside it).

    name picks each file's name (given the names taken so far). Returns the text and,
    for each file, its name and either its sha256 (a stored file) or its bytes.
    """
    front = {
        key: page[key] for key in ("title", "id", "kind", "created_at", "updated_at")
    }
    front["fields"] = json.loads(page["fields"])
    lines = ["---", *(f"{k}: {json.dumps(v)}" for k, v in front.items())]
    lines += ["---", "", page["body"], ""]
    files: list[tuple[str, str | bytes]] = []
    taken: set[str] = set()
    for blob in conn.execute(
        "SELECT b.sha256, b.mime, cb.filename, c.id AS capture_id FROM capture c"
        " JOIN capture_blob cb ON cb.capture_id = c.id"
        " JOIN blob b USING (sha256)"
        " WHERE c.page_id = ? ORDER BY c.received_at, cb.ord",
        (page["id"],),
    ):
        file = name(blob, taken)
        taken.add(file)
        files.append((file, blob["sha256"]))
        label = (blob["filename"] or file).replace("[", "(").replace("]", ")")
        image = "!" if blob["mime"].startswith("image/") else ""
        lines.append(f"{image}[{label}](files/{quote(file)})")
        if not image:
            continue
        got = _derived(conn, blob["capture_id"], blob["sha256"])
        if "description" in got and got["description"]["text"]:
            lines += ["", f"> {got['description']['text']}".replace("\n", "\n> ")]
        if "ocr" in got and got["ocr"]["text"]:
            lines += ["", *_fenced(got["ocr"]["text"])]
        if "excalidraw" in got:
            # scrap export puts every page's files in one folder, named by content: a
            # photo is the same file on every page, but its drawing is per capture
            stem = file.rpartition(".")[0] or file
            if name is _sha_name:
                stem = f"{blob['sha256']}-{blob['capture_id']}"
            drawing = _drawing_name(stem, taken)
            taken.add(drawing)
            data = json.loads(got["excalidraw"]["data"])
            files.append((drawing, excalidraw_file(data)))
            lines += ["", f"[Drawing of {label}](files/{quote(drawing)})"]
        if len(got):
            lines.append("")
    return "\n".join(lines) + "\n", files


def _drawing_name(stem: str, taken: set[str]) -> str:
    """<stem>.excalidraw, numbered if that is taken."""
    seen = {t.casefold() for t in taken}
    name, n = f"{stem}.excalidraw", 1
    while name.casefold() in seen:
        n += 1
        name = f"{stem}-{n}.excalidraw"
    return name


def export(store: Store, dest: Path) -> int:
    """Write a Markdown file per page, its originals in files/; return the count."""
    if not store.db.is_file():
        raise SystemExit(f"no database at {store.db}")
    (dest / "files").mkdir(parents=True, exist_ok=True)
    with store.connect() as conn:
        pages = conn.execute(
            "SELECT * FROM page WHERE deleted_at IS NULL ORDER BY created_at"
        ).fetchall()
        for page in pages:
            text, files = page_markdown(conn, page)
            for name, content in files:
                if isinstance(content, bytes):  # made here, e.g. a drawing
                    (dest / "files" / name).write_bytes(content)
                elif not (dest / "files" / name).exists():
                    shutil.copy2(store.blob_path(content), dest / "files" / name)
            (dest / f"{page['slug']}.md").write_text(text)
    return len(pages)


def file_name(name: str | None, sha: str, mime: str) -> str:
    """A safe file name for a stored file: its own name, else one from its hash."""
    name = re.sub(r"[^\w. -]+", "_", (name or "").rsplit("/", 1)[-1].rsplit("\\")[-1])
    stem, dot, ext = name.strip(" .").rpartition(".")
    if not stem or len(ext) > 10:  # no extension, or not one: all stem
        stem, dot, ext = f"{stem}{dot}{ext}", "", ""
    name = f"{stem[: 120 - len(dot + ext)].rstrip(' .')}{dot}{ext}"  # keep its type
    return name if stem else sha[:12] + (mimetypes.guess_extension(mime) or "")


def _friendly_name(blob: sqlite3.Row, taken: set[str]) -> str:
    name = file_name(blob["filename"], blob["sha256"], blob["mime"])
    stem, dot, ext = name.rpartition(".")
    if not stem:
        stem, dot, ext = ext, "", ""
    seen = {t.casefold() for t in taken}  # photo.jpg and PHOTO.jpg are one file to many
    n = 1
    while name.casefold() in seen:
        n += 1
        name = f"{stem}-{n}{dot}{ext}"
    return name


def download(store: Store, key: str, out: IO[bytes]) -> tuple[str, str]:
    """Write one page to out: <slug>.md, or with files a <slug>.zip of the Markdown and
    files/ (relative links, so it reads offline). Returns the file name and type."""
    with store.connect() as conn:
        page = conn.execute(
            "SELECT * FROM page WHERE (id = ? OR slug = ?) AND deleted_at IS NULL",
            (key, key),
        ).fetchone()
        if page is None:
            raise NotFoundError(key)
        text, files = page_markdown(conn, page, _friendly_name)
    slug = page["slug"]
    if not files:
        out.write(text.encode())
        return f"{slug}.md", "text/markdown; charset=utf-8"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(f"{slug}.md", text, zipfile.ZIP_DEFLATED)
        for name, content in files:  # photos are compressed already: stored as is
            if isinstance(content, bytes):
                zf.writestr(f"files/{name}", content, zipfile.ZIP_DEFLATED)
            else:
                zf.write(store.blob_path(content), f"files/{name}", zipfile.ZIP_STORED)
    return f"{slug}.zip", "application/zip"
