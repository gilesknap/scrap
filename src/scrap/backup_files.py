"""A backup run's files/: each blob hard-linked from an earlier complete run when that
run has it, copied otherwise (issue 570).

Blobs are content-addressed and never change once written, so a file in an earlier run
whose bytes hash to its name holds what the live file holds. Each one is hashed before
it is linked, so a damaged blob in an earlier run is copied afresh from the live store,
not carried forward. A link costs no space: each run still looks like, and restores as,
a full copy, and pruning a run only drops its links. Nothing writes into a run once it
is complete: restore copies out of it (a new file), so the live store never shares an
inode with a backup.
"""

import hashlib
import logging
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from .store import SHA256

__all__ = ["FileCounts", "copy_files"]

log = logging.getLogger(__name__)


@dataclass
class FileCounts:
    """What a run's files/ took: files linked from base, and files copied."""

    base: Path | None = None  # the earlier run linked from, if any
    linked: int = 0
    linked_bytes: int = 0
    copied: int = 0
    copied_bytes: int = 0
    damaged: int = 0  # files in base whose bytes do not match their name

    def __str__(self) -> str:
        mb = 1024 * 1024
        text = f"files: {self.copied} copied ({self.copied_bytes / mb:.1f} MB)"
        if self.base:
            text += (
                f", {self.linked} linked from {self.base.name}"
                f" ({self.linked_bytes / mb:.1f} MB)"
            )
        if self.damaged:
            text += f", {self.damaged} damaged there copied afresh"
        return text


def copy_files(src: Path, dest: Path, base: Path | None = None) -> FileCounts:
    """Copy the blobs in src into dest (a file already in dest is left alone), linking
    each from base/files when it has that blob: a regular file of this process's user,
    the same size, whose bytes hash to its name, in no symlinked folder. A link that
    fails (another filesystem, one without hard links, too many links) is a copy."""
    counts = FileCounts(base)
    files = _base_files(base) if base else None
    uid = os.getuid()
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dest / rel
        if not path.is_file() or path.name.startswith(".") or target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        size = path.stat().st_size
        if files and _link(files, rel, target, size, uid, counts):
            counts.linked += 1
            counts.linked_bytes += size
        else:
            _copy(path, target)
            counts.copied += 1
            counts.copied_bytes += size
    return counts


def _base_files(base: Path) -> Path | None:
    """base/files, if neither it nor base is a symlink."""
    files = base / "files"
    try:
        if all(stat.S_ISDIR(p.lstat().st_mode) for p in (base, files)):
            return files
    except OSError:
        pass
    return None


def _link(
    files: Path, rel: Path, target: Path, size: int, uid: int, counts: FileCounts
) -> bool:
    """Hard-link files/rel to target if it is the blob rel names; False if not."""
    folder, name = rel.parts if len(rel.parts) == 2 else ("", "")
    if not SHA256.fullmatch(name) or name[:2] != folder:
        return False
    old = files / rel
    try:
        if not stat.S_ISDIR((files / folder).lstat().st_mode):  # a symlink, say
            return False
        info = old.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != size or info.st_uid != uid:
            return False
        with old.open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != name:
                log.warning("backup: %s does not match its name; copied afresh", old)
                counts.damaged += 1
                return False
        os.link(old, target)
    except OSError:  # EXDEV, EPERM, EMLINK, ENOTSUP and the like: copy instead
        return False
    return True


def _copy(path: Path, target: Path) -> None:
    """Copy under a dot name, then rename: a copy cut short never has the blob's name
    (a re-run would take it as there), and dot names are never copied or linked."""
    part = target.with_name(f".{target.name}.part")
    try:
        shutil.copy2(path, part)
        part.replace(target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
