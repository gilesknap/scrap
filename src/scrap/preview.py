"""JPEG previews of stored photos, made on first request and kept as a cache.

The cache (``cache/previews`` in the data folder) is never backed up: any of it can be
deleted and is made again. Originals are never changed.
"""

import os
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from .store import InvalidError, Store

__all__ = ["SIZES", "preview"]

SIZES = (480, 2048)  # longest side: lists, and the page and viewer
MAX_PIXELS = (
    120_000_000  # bigger is refused rather than decoded (a 108 MP phone is fine)
)
Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # Pillow's own check: an error at twice this
register_heif_opener()  # iPhone HEIC photos
_busy = threading.BoundedSemaphore(2)  # decoding a big photo takes ~0.5 GB at worst


def _make(src: Path, dest: Path, size: int) -> None:
    try:
        with Image.open(src) as im:
            if im.width * im.height > MAX_PIXELS:
                raise InvalidError("image too large to preview")
            im.draft("RGB", (size, size))  # a JPEG decodes at a fraction of its size
            im = ImageOps.exif_transpose(im)  # turn it the way the camera held it
            if im.mode not in ("RGB", "L"):
                rgba = im.convert("RGBA")  # transparency onto white
                im = Image.new("RGB", rgba.size, "white")
                im.paste(rgba, mask=rgba.getchannel("A"))
            im.thumbnail((size, size), Image.Resampling.LANCZOS, reducing_gap=3.0)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as tmp:
                try:
                    im.save(tmp, "JPEG", quality=82, progressive=True)  # no EXIF kept
                    tmp.close()
                    os.replace(tmp.name, dest)
                except BaseException:
                    os.unlink(tmp.name)
                    raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,  # if warnings are errors
        OSError,
        ValueError,
    ):
        raise InvalidError("cannot preview this file") from None


def preview(store: Store, sha: str, size: int) -> Path:
    """The path of a JPEG preview of a stored image, at most size pixels a side."""
    if size not in SIZES:
        raise InvalidError(f"size must be one of {SIZES}")
    src, mime = store.blob(sha)  # checks sha is a SHA-256 we hold
    if not mime.startswith("image/"):
        raise InvalidError("not an image")
    dest = store.dir / "cache" / "previews" / str(size) / sha[:2] / f"{sha}.jpg"
    if not dest.is_file():
        with _busy:
            if not dest.is_file():  # made while this one waited
                _make(src, dest, size)
    return dest
