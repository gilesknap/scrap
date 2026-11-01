"""scrap's copies of what it pushed (docs/reference/public-site.md, "scrap's copies"):
under ``<data>/cache/publish/``, each published page's unit exactly as last pushed,
``p/<slug>/`` (its index.html, img-* and file-*), with ``meta.json`` beside them (not
part of the unit), and ``digests.json``: the digest scrap last pushed for every unit.
Derived data, not backed up: the site's home, tag and search units are built from
these copies alone, and reconcile refills a site that lost its files from them.

Nothing here locks: the Publisher holds its lock over every use."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

__all__ = ["META", "Kept"]

META = "meta.json"
DIGESTS = "digests.json"


class Kept:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.pages = root / "p"

    def _dir(self, slug: str) -> Path:
        return self.pages / slug

    def slugs(self) -> list[str]:
        """The slugs with a kept copy, sorted."""
        if not self.pages.is_dir():
            return []
        return sorted(
            p.name for p in self.pages.iterdir() if p.is_dir() and "." not in p.name
        )

    def meta(self, slug: str) -> dict[str, Any] | None:
        """A copy's meta.json ({id, title, tags, published_at}), None if there
        is no copy or it is unreadable."""
        try:
            data = json.loads((self._dir(slug) / META).read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def files(self, slug: str) -> dict[str, bytes]:
        """A copy's unit files, by name (meta.json is not one)."""
        folder = self._dir(slug)
        if not folder.is_dir():
            return {}
        return {
            p.name: p.read_bytes()
            for p in sorted(folder.iterdir())
            if p.is_file() and p.name != META
        }

    def html(self, slug: str) -> bytes:
        """A copy's index.html (empty if there is none)."""
        try:
            return (self._dir(slug) / "index.html").read_bytes()
        except OSError:
            return b""

    def incomplete(self, slug: str) -> bool:
        """Whether a copy lacks its meta.json, its digest or its index.html (read
        nothing else)."""
        return (
            self.meta(slug) is None
            or self.digest(f"p/{slug}") is None
            or not (self._dir(slug) / "index.html").is_file()
        )

    def write(
        self, slug: str, files: dict[str, bytes], meta: dict[str, Any], dig: str
    ) -> None:
        """Keep a page's unit as pushed, replacing its last copy whole, and its
        digest."""
        self.pages.mkdir(parents=True, exist_ok=True)
        new = Path(tempfile.mkdtemp(dir=self.pages, prefix=".new-"))
        for name, content in files.items():
            (new / name).write_bytes(content)
        (new / META).write_text(json.dumps(meta, sort_keys=True))
        folder = self._dir(slug)
        if folder.exists():
            old = Path(tempfile.mkdtemp(dir=self.pages, prefix=".old-"))
            os.replace(folder, old / slug)
            os.replace(new, folder)
            shutil.rmtree(old, ignore_errors=True)
        else:
            os.replace(new, folder)
        self.set_digest(f"p/{slug}", dig)

    def delete(self, slug: str) -> bool:
        """Delete a page's copy and its digest; whether there was one."""
        folder = self._dir(slug)
        had = folder.exists()
        if had:
            shutil.rmtree(folder)
        self.drop_digest(f"p/{slug}")
        return had

    def clean(self) -> None:
        """Remove what an interrupted write left (.new-*, .old-*)."""
        if self.pages.is_dir():
            for p in self.pages.iterdir():
                if p.name.startswith("."):
                    shutil.rmtree(p, ignore_errors=True)

    # The digest last pushed for each unit
    def digests(self) -> dict[str, str]:
        try:
            data = json.loads((self.root / DIGESTS).read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def digest(self, unit: str) -> str | None:
        return self.digests().get(unit)

    def _save(self, digests: dict[str, str]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f".{DIGESTS}.tmp"
        tmp.write_text(json.dumps(digests, sort_keys=True, indent=0))
        os.replace(tmp, self.root / DIGESTS)

    def set_digest(self, unit: str, dig: str) -> None:
        self._save({**self.digests(), unit: dig})

    def drop_digest(self, unit: str) -> None:
        digests = self.digests()
        if digests.pop(unit, None) is not None:
            self._save(digests)
