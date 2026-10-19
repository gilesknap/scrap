"""Backup, restore and Markdown export of a data folder."""

import json
import mimetypes
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from .store import Store, connect, migrate, schema_version

__all__ = ["backup", "restore", "export"]


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

    The backup is checked and migrated in a copy beside the live database, which
    is swapped in only at the end. Files are only ever added.
    """
    backup_db = src / "scrap.db"
    if not backup_db.is_file():
        raise SystemExit(f"no backup at {src}")
    used = store.db.exists() or (store.files.is_dir() and any(store.files.iterdir()))
    if used and not force:
        raise SystemExit(f"{store.dir} is not empty; stop scrap and use --force")
    try:
        schema_version(backup_db)  # refuses a backup newer than this scrap
        with closing(connect(backup_db)) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except (RuntimeError, sqlite3.DatabaseError) as error:
        raise SystemExit(f"bad backup: {error}") from None
    if check != "ok":
        raise SystemExit(f"bad backup: integrity_check says {check}")
    store.files.mkdir(parents=True, exist_ok=True)
    _copy_files(src / "files", store.files)
    part = store.dir / "scrap.db.restore"
    _snapshot(backup_db, part)
    migrate(part)
    Path(f"{part}.lock").unlink()
    for suffix in ("-wal", "-shm"):
        Path(f"{store.db}{suffix}").unlink(missing_ok=True)
    part.replace(store.db)


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
            front = {
                key: page[key]
                for key in ("title", "id", "kind", "created_at", "updated_at")
            }
            front["fields"] = json.loads(page["fields"])
            lines = ["---", *(f"{k}: {json.dumps(v)}" for k, v in front.items())]
            lines += ["---", "", page["body"], ""]
            for blob in conn.execute(
                "SELECT b.sha256, b.mime, cb.filename FROM capture c"
                " JOIN capture_blob cb ON cb.capture_id = c.id"
                " JOIN blob b USING (sha256)"
                " WHERE c.page_id = ? ORDER BY c.received_at, cb.ord",
                (page["id"],),
            ):
                name = blob["sha256"] + (mimetypes.guess_extension(blob["mime"]) or "")
                if not (dest / "files" / name).exists():
                    shutil.copy2(store.blob_path(blob["sha256"]), dest / "files" / name)
                label = (blob["filename"] or name).replace("[", "(").replace("]", ")")
                image = "!" if blob["mime"].startswith("image/") else ""
                lines.append(f"{image}[{label}](files/{name})")
            (dest / f"{page['slug']}.md").write_text("\n".join(lines) + "\n")
    return len(pages)
