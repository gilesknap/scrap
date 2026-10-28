"""Backup, restore and Markdown export of a data folder."""

import json
import mimetypes
import re
import shutil
import sqlite3
import zipfile
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import IO
from urllib.parse import quote, unquote

from .drawing import excalidraw_file
from .page_notes import Extras, file_text, gather
from .preview import preview
from .store import (
    InvalidError,
    NoSuchPage,
    Store,
    connect,
    migrate,
    schema_version,
)
from .store.todo import read as read_todo

__all__ = ["backup", "restore", "export", "page_markdown", "download", "file_name"]

# Written last into a backup run; gc deletes only after a run that has one
COMPLETE = "COMPLETE"

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


def _check(db: Path) -> None:
    """Refuse a snapshot SQLite finds damaged (read-only: it leaves no -wal behind)."""
    uri = f"{db.resolve().as_uri()}?immutable=1"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as error:
        check = str(error)
    if check != "ok":
        raise SystemExit(f"backup in {db.parent} is damaged: integrity_check: {check}")


def backup(store: Store, dest: Path) -> None:
    """Snapshot the database, then copy files/; safe while scrap is serving.

    Blobs are written before the transaction that records them, so every blob the
    snapshot names is already in files/ when the copy starts. The snapshot is then
    checked, and only a good one gets a COMPLETE marker: deploy/scrap-gc and the gc
    CronJob count a run without it as no backup. A refused backup leaves no marker.
    """
    if not store.db.is_file():
        raise SystemExit(f"no database at {store.db}")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / COMPLETE).unlink(missing_ok=True)  # a re-run into a run dir starts unproven
    _snapshot(store.db, dest / "scrap.db")
    _copy_files(store.files, dest / "files")
    _check(dest / "scrap.db")
    part = dest / f"{COMPLETE}.part"
    part.write_text(f"{datetime.now(UTC).isoformat()}\n")
    part.replace(dest / COMPLETE)


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
        _restore_into(src, store, part)
    except BaseException:  # a refusal or Ctrl-C: leave no backup-sized leftover
        _discard(part)
        if created and not store.db.exists():  # not once the swap has happened
            shutil.rmtree(store.dir, ignore_errors=True)
        raise


def _restore_into(src: Path, store: Store, part: Path) -> None:
    backup_db = src / "scrap.db"
    _discard(part)
    try:
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
        what = "cannot copy the backup" if isinstance(error, OSError) else "bad backup"
        # Name the folder the user gave, not the temporary copy
        reason = str(error).replace(str(part), str(src))
        raise SystemExit(f"{what}: {reason}") from None
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


# A Markdown link or image to a file of this server, by its address
OWN_BLOB = re.compile(
    r"(!?)\[([^\[\]\n]*)\]\(/api/blobs/([0-9a-f]{64})"
    r"(?:/preview\?size=\d+|\?download=1)?\)"
)
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
# (?<!`) first: a run of backticks is tried from its start only, so many unmatched runs
# cost linear time, not quadratic (as web/src/md.ts)
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)")


def _outside_code(text: str, change: Callable[[str], str]) -> str:
    """text with change applied to all but its code: fenced blocks and code spans."""
    out: list[str] = []
    close: re.Pattern[str] | None = None  # what ends the open fence
    for line in text.split("\n"):
        if close:
            if close.fullmatch(line):
                close = None
        elif opened := FENCE.match(line):
            mark = opened[1]
            close = re.compile(rf" {{0,3}}{re.escape(mark[0])}{{{len(mark)},}}\s*")
        else:
            at, parts = 0, []
            for span in CODE_SPAN.finditer(line):
                parts += [change(line[at : span.start()]), span[0]]
                at = span.end()
            line = "".join([*parts, change(line[at:])])
        out.append(line)
    return "\n".join(out)


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
    conn: sqlite3.Connection,
    page: sqlite3.Row,
    name: Namer = _sha_name,
    extras: Extras | None = None,
) -> tuple[str, list[tuple[str, str | bytes]]]:
    """A page as Markdown: front matter, its body, then a link per file under files/,
    each photo followed by what Claude made of it (its description, the text it read
    and the drawing, as an .excalidraw file beside it).

    name picks each file's name (given the names taken so far). Returns the text and,
    for each file, its name and either its sha256 (a stored file) or its bytes.

    extras (a single page's download, not `scrap export`) adds the page's tags, status
    and topics to the front matter, the text read from its PDFs and text files, then
    Claude's notes and what links here, and writes `[[slug]]` links as full addresses.
    """
    front = {
        key: page[key] for key in ("title", "id", "kind", "created_at", "updated_at")
    }
    if page["kind"] == "todo":  # a todo's due date and priority, if it has them
        front |= {k: v for k, v in read_todo(conn, page["id"]).items() if v}
    if page["task_total"]:  # its task boxes, as counted
        front["tasks"] = {"done": page["task_done"], "total": page["task_total"]}
    front |= extras.front if extras else {}
    front["fields"] = json.loads(page["fields"])
    lines = ["---", *(f"{k}: {json.dumps(v)}" for k, v in front.items())]
    files: list[tuple[str, str | bytes]] = []
    taken: set[str] = set()
    blobs = conn.execute(
        "SELECT b.sha256, b.mime, cb.filename, c.id AS capture_id FROM capture c"
        " JOIN capture_blob cb ON cb.capture_id = c.id"
        " JOIN blob b USING (sha256)"
        " WHERE c.page_id = ? ORDER BY c.received_at, cb.ord",
        (page["id"],),
    ).fetchall()
    names: dict[str, str] = {}  # each file's name here, by sha256
    local: dict[str, tuple[str, str]] = {}  # and its address and label
    for blob in blobs:
        sha = blob["sha256"]
        if sha not in names:  # the same file in two captures: one copy
            names[sha] = file = name(blob, taken)
            taken.add(file)
            files.append((file, sha))
            label = (blob["filename"] or "").replace("[", "(").replace("]", ")")
            local[sha] = (f"files/{quote(file)}", label)

    shown: set[str] = set()  # files the text shows as images

    # The text's images point at the files here, named. Another page's file is only in
    # an export (one files/ folder for all): there it is added, else left as it is.
    def here(m: re.Match[str]) -> str:
        sha = m[3]
        if sha not in local and name is _sha_name:
            row = conn.execute(
                "SELECT sha256, mime, NULL AS filename FROM blob WHERE sha256 = ?",
                (sha,),
            ).fetchone()
            if row:
                file = name(row, taken)
                files.append((file, sha))
                local[sha] = (f"files/{quote(file)}", "")
        if sha not in local:
            return m[0]
        if m[1]:
            shown.add(sha)
        address, label = local[sha]
        # No alt: the name it was uploaded under; if the file has none (another page's,
        # or a bare sha) an image keeps its alt empty, not a 64-hex name, while a link
        # (which needs text to show) gets the file's name
        text = m[2] or label or ("" if m[1] else unquote(address.split("/", 1)[1]))
        return f"{m[1]}[{text}]({address})"

    body = _outside_code(page["body"], lambda t: OWN_BLOB.sub(here, t))
    if extras:
        body = extras.links(body)
    lines += ["---", "", body, ""]
    listed: set[str] = set()
    for blob in blobs:
        sha = blob["sha256"]
        file = names[sha]
        label = (blob["filename"] or file).replace("[", "(").replace("]", ")")
        image = blob["mime"].startswith("image/")
        got = _derived(conn, blob["capture_id"], sha) if image else {}
        # Each file once; an image the text shows is only named, before Claude's notes
        if sha not in shown and sha not in listed:
            lines.append(f"{'!' if image else ''}[{label}](files/{quote(file)})")
        elif got:
            lines.append(f"[{label}](files/{quote(file)})")
        listed.add(sha)
        if extras and not image and (text := file_text(conn, blob["capture_id"], sha)):
            cut = "\n[text cut here]" if text[1] else ""
            lines += ["", *_fenced(text[0] + cut), ""]
        if not image:
            continue
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
    if extras:
        if extras.notes:
            lines += ["", *extras.notes]
        if extras.linked_from:
            lines += ["", "## Linked from", "", *extras.linked_from]
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


def _friendly_name(blob: sqlite3.Row, taken: set[str], jpeg: bool = False) -> str:
    name = file_name(blob["filename"], blob["sha256"], blob["mime"])
    if jpeg and blob["mime"].startswith("image/"):  # its preview is a JPEG
        name = f"{name.rpartition('.')[0] or name}.jpg"
    stem, dot, ext = name.rpartition(".")
    if not stem:
        stem, dot, ext = ext, "", ""
    seen = {t.casefold() for t in taken}  # photo.jpg and PHOTO.jpg are one file to many
    n = 1
    while name.casefold() in seen:
        n += 1
        name = f"{stem}-{n}{dot}{ext}"
    return name


def _preview_name(blob: sqlite3.Row, taken: set[str]) -> str:
    return _friendly_name(blob, taken, jpeg=True)


PREVIEW_SIZE = 2048  # the longest side of a photo in a download with previews


def download(
    store: Store,
    key: str,
    out: IO[bytes],
    notes: bool = True,
    previews: bool = False,
) -> tuple[str, str]:
    """Write one page to out: <slug>.md, or with files a <slug>.zip of the Markdown and
    files/ (relative links, so it reads offline). Returns the file name and type.

    The Markdown has the page's tags, status and topics, the text read from its PDFs
    and text files, what links here and, unless notes is false, Claude's notes
    (page_notes). With previews each photo is its 2048 pixel JPEG preview (no EXIF or
    GPS, smaller), not the original; one that cannot be previewed is left out. Raises
    BusyError (preview) if the photo decoder stays busy."""
    with store.connect() as conn:
        page = conn.execute(
            "SELECT * FROM page WHERE (id = ? OR slug = ?) AND deleted_at IS NULL",
            (key, key),
        ).fetchone()
        if page is None:
            raise NoSuchPage(key)
        extras = gather(store, conn, page["id"], notes)
        namer = _preview_name if previews else _friendly_name
        text, files = page_markdown(conn, page, namer, extras)
    slug = page["slug"]
    if not files:
        out.write(text.encode())
        return f"{slug}.md", "text/markdown; charset=utf-8"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(f"{slug}.md", text, zipfile.ZIP_DEFLATED)
        for name, content in files:  # photos are compressed already: stored as is
            if isinstance(content, bytes):
                zf.writestr(f"files/{name}", content, zipfile.ZIP_DEFLATED)
                continue
            path = store.blob_path(content)
            if previews and store.blob(content)[1].startswith("image/"):
                try:
                    path = preview(store, content, PREVIEW_SIZE)
                except InvalidError:
                    continue  # not an image it can decode: not shared as the original
            zf.write(path, f"files/{name}", zipfile.ZIP_STORED)
    return f"{slug}.zip", "application/zip"
