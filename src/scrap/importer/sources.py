"""What is imported from: a folder or a zip, read in place.

A zip's entries are read by name and never extracted, so a name cannot write
anywhere; still, an archive with a name that would climb out of it (`../x`, `/x`,
`C:x`, a backslash) is refused whole, as is one with more than MAX_ENTRIES files or
more bytes in them than it may hold. A folder's symlinks are never followed."""

import os
import stat
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from .model import MAX_ENTRIES, MAX_TOTAL


class RefusedError(Exception):
    """An archive or folder that is not imported at all, and why."""


@dataclass
class Entry:
    size: int
    mtime: datetime  # UTC


def safe_name(name: str) -> bool:
    """Whether a zip entry's name stays inside the archive: relative, forward slashes,
    no `..`, no drive, no NUL."""
    if not name or "\\" in name or "\0" in name or name.startswith("/"):
        return False
    parts = name.rstrip("/").split("/")
    return ":" not in parts[0] and all(p not in ("", ".", "..") for p in parts)


def _hidden(part: str) -> bool:
    """A folder an import never enters: Obsidian's settings (.obsidian), git's, and
    `_`-prefixed ones (scrap's _claude, model text that never becomes a page)."""
    return part.startswith((".", "_"))


class Source:
    """The files to import, by path from the top ("a/b.md"), each with its size and
    time; reading one never goes outside."""

    def __init__(self) -> None:
        self.files: dict[str, Entry] = {}
        self.dropped: set[str] = set()  # the hidden folders, not read
        self.unsafe: list[str] = []  # symlinks and the like, not read

    def _add(self, rel: str, entry: Entry) -> None:
        parts = rel.split("/")
        hidden = [i for i, p in enumerate(parts[:-1]) if _hidden(p)]
        if hidden:
            self.dropped.add("/".join(parts[: hidden[0] + 1]))
        elif not parts[-1].startswith("."):  # .DS_Store and the like
            self.files[rel] = entry

    def read(self, rel: str, most: int) -> bytes | None:
        """A file's bytes, or None if it holds more than most."""
        if self.files[rel].size > most:
            return None
        with self.open(rel) as f:
            data = f.read(most + 1)
        return None if len(data) > most else data

    @contextmanager
    def open(self, rel: str) -> Iterator[IO[bytes]]:
        raise NotImplementedError
        yield  # pragma: no cover

    def close(self) -> None:
        pass


class Folder(Source):
    def __init__(self, root: Path):
        super().__init__()
        self.root = root.resolve()
        count = 0
        for top, dirs, names in os.walk(self.root):  # never into a symlinked folder
            here = Path(top)
            for d in list(dirs):
                rel = (here / d).relative_to(self.root).as_posix()
                if (here / d).is_symlink():
                    self.unsafe.append(rel)
                    dirs.remove(d)
                elif _hidden(d):  # not walked
                    self.dropped.add(rel)
                    dirs.remove(d)
            for name in sorted(names):
                path = here / name
                rel = path.relative_to(self.root).as_posix()
                st = path.lstat()
                if not stat.S_ISREG(st.st_mode):
                    self.unsafe.append(rel)
                    continue
                count += 1
                if count > MAX_ENTRIES:
                    raise RefusedError(f"more than {MAX_ENTRIES:,} files")
                when = datetime.fromtimestamp(st.st_mtime, UTC)
                self._add(rel, Entry(st.st_size, when))
            dirs.sort()

    @contextmanager
    def open(self, rel: str) -> Iterator[IO[bytes]]:
        path = self.root / rel
        # O_NOFOLLOW: a file swapped for a symlink since the walk is not read
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as f:
            yield f


class Archive(Source):
    def __init__(self, file: Path | IO[bytes], total: int = MAX_TOTAL):
        super().__init__()
        try:
            self.zip = zipfile.ZipFile(file)
        except (zipfile.BadZipFile, OSError) as e:
            raise RefusedError(f"not a zip file ({e})") from None
        try:
            infos = self.zip.infolist()
            if len(infos) > MAX_ENTRIES:
                raise RefusedError(f"more than {MAX_ENTRIES:,} files")
            held = 0
            for info in infos:
                if not safe_name(info.filename):
                    raise RefusedError(f"a file named {info.filename[:80]!r}")
                if info.is_dir():
                    continue
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    self.unsafe.append(info.filename)
                    continue
                held += info.file_size
                if held > total:
                    raise RefusedError(
                        f"its files hold more than {total / 2**30:g} GB unpacked"
                    )
                when = datetime(*info.date_time, tzinfo=UTC)
                self._add(info.filename, Entry(info.file_size, when))
        except BaseException:
            self.zip.close()
            raise

    @contextmanager
    def open(self, rel: str) -> Iterator[IO[bytes]]:
        # Never more than its stated size: zipfile stops there, and checks the CRC
        with self.zip.open(rel) as f:
            yield f

    def close(self) -> None:
        self.zip.close()


def source(path: Path | IO[bytes], total: int = MAX_TOTAL) -> Source:
    """A folder or a zip (a path, or an open file) to import from."""
    if isinstance(path, Path) and path.is_dir():
        return Folder(path)
    if isinstance(path, Path) and not path.is_file():
        raise RefusedError(f"no folder or zip file {path}")
    return Archive(path, total)
