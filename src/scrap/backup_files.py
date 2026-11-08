"""A backup run's files/: each blob hard-linked from an earlier complete run when that
run has it, copied otherwise (issue 570).

Blobs are content-addressed and never change once written, so a file of the same name
(and size, a cheap guard) in an earlier run holds the same bytes. A link costs no space:
each run still looks like, and restores as, a full copy, and pruning a run only drops
its links. Nothing writes into a run once it is complete: restore copies out of it
(shutil.copy2, a new file), so the live store never shares an inode with a backup.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

__all__ = ["FileCounts", "copy_files"]


@dataclass
class FileCounts:
    """What a run's files/ took: files linked from base, and files copied."""

    base: Path | None = None  # the earlier run linked from, if any
    linked: int = 0
    linked_bytes: int = 0
    copied: int = 0
    copied_bytes: int = 0

    def __str__(self) -> str:
        mb = 1024 * 1024
        text = f"files: {self.copied} copied ({self.copied_bytes / mb:.1f} MB)"
        if self.base:
            text += (
                f", {self.linked} linked from {self.base.name}"
                f" ({self.linked_bytes / mb:.1f} MB)"
            )
        return text


def copy_files(src: Path, dest: Path, base: Path | None = None) -> FileCounts:
    """Copy the blobs in src into dest (a file already in dest is left alone), linking
    each from base/files when it has a file of that name and size. A link that fails
    (another filesystem, one without hard links, too many links) is a copy."""
    counts = FileCounts(base)
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dest / rel
        if not path.is_file() or path.name.startswith(".") or target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        size = path.stat().st_size
        if base and _link(base / "files" / rel, target, size):
            counts.linked += 1
            counts.linked_bytes += size
        else:
            shutil.copy2(path, target)
            counts.copied += 1
            counts.copied_bytes += size
    return counts


def _link(old: Path, target: Path, size: int) -> bool:
    """Hard-link old to target if old is a file of this size; False if not linked."""
    try:
        if not old.is_file() or old.is_symlink() or old.stat().st_size != size:
            return False
        os.link(old, target)
    except OSError:  # EXDEV, EPERM, EMLINK, ENOTSUP and the like: copy instead
        return False
    return True
