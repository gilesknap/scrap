"""One unit of the public site as the receiver takes it (scrap-public/receiver.py):
a plain tar of regular files and its ``Scrap-Digest``.

The digest is the sha256, in hex, of one line per file in sorted path order,
``path NUL sha256hex(content) LF``. The receiver recomputes it from what it
unpacked and answers 400 when it differs. The contract is
docs/reference/public-site.md, which also says what each kind of unit may hold.

Stdlib only: the receiver's tests build their uploads with it too.
"""

import hashlib
import io
import re
import tarfile

__all__ = ["SEGMENT", "UnitError", "build_unit", "digest"]

# One path segment of a file in a unit; a path has at most MAX_DEPTH of them
SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
MAX_DEPTH = 4


class UnitError(ValueError):
    """A file path the receiver would refuse (422)."""


def digest(files: dict[str, bytes]) -> str:
    """The ``Scrap-Digest`` of these files: the receiver's own computation."""
    lines = b"".join(
        path.encode() + b"\0" + hashlib.sha256(files[path]).hexdigest().encode() + b"\n"
        for path in sorted(files)
    )
    return hashlib.sha256(lines).hexdigest()


def build_unit(files: dict[str, bytes]) -> tuple[bytes, str]:
    """A unit's upload body (an uncompressed tar holding only regular files, in
    sorted order, with fixed owner, mode and time) and its ``Scrap-Digest``.

    ``files`` maps a path inside the unit (``index.html``, ``files/report.pdf``) to
    its content. A path the receiver would refuse raises UnitError; the extension
    allow-list and the size limits are the receiver's to check."""
    if not files:
        raise UnitError("a unit holds at least one file")
    for path in files:
        parts = path.split("/")
        if len(parts) > MAX_DEPTH or not all(SEGMENT.fullmatch(p) for p in parts):
            raise UnitError(f"not a valid path in a unit: {path!r}")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(files):
            content = files[path]
            info = tarfile.TarInfo(path)
            info.size = len(content)
            info.mode = 0o644
            info.mtime = 0
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue(), digest(files)
