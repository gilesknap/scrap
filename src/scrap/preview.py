"""JPEG previews of stored photos, made on first request and kept as a cache.

The cache (``cache/previews`` in the data folder) is never backed up: any of it can be
deleted and is made again. Originals are never changed.

Memory: scrap runs in a 1 GB container, and decoding a photo needs all its pixels in
memory at once. So a photo is shrunk straight after decoding, before anything else
copies it; a JPEG is even decoded at 1/2 to 1/8 scale. Photos whose decode would need
more than DECODE_BUDGET are refused (the app shows the original instead), and one
photo is decoded at a time.
"""

import os
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from .store import InvalidError, Store

__all__ = ["SIZES", "BusyError", "preview"]

SIZES = (480, 2048)  # longest side: lists, and the page and viewer
# Bytes one decode may take, as estimated by _cost: about 50 MP for a HEIC (an iPhone's
# 48 MP fits), 80 MP for a PNG, 47 MP with transparency; a JPEG is decoded shrunk, so
# even 120 MP fits. Measured peak RSS over the process's own: 48 MP HEIC 330 MB, 12 MP
# HEIC 90 MB, 40 MP PNG 200 MB (with transparency 355 MB), 100 MP PNG 470 MB (refused
# now), 120 MP JPEG 60 MB.
DECODE_BUDGET = 400 * 2**20
WAIT = 20  # seconds a request waits for the decoder before a 503
Image.MAX_IMAGE_PIXELS = 200_000_000  # Pillow's own bomb check: far past the budget
register_heif_opener()  # iPhone HEIC photos
_decoder = threading.Lock()  # one decode at a time: two big ones would not fit


class BusyError(Exception):
    """Another preview is being made: try again shortly."""


def _cost(im: Image.Image) -> int:
    """Bytes decoding im is expected to take at its peak (from what it decodes to, not
    its size on disk), as measured: a pixel of a colour image takes 4 bytes in Pillow,
    and shrinking one with transparency makes premultiplied copies."""
    pixels = im.width * im.height
    if im.format == "HEIF":
        return pixels * 8  # libheif's YCbCr planes as well as the RGB
    alpha = "A" in im.getbands() or "transparency" in im.info
    if len(im.getbands()) > 1 or im.mode in ("P", "1"):
        store = 4
    else:
        store = 2 if im.mode.startswith("I;16") else 4 if im.mode in ("I", "F") else 1
    return int(pixels * store * (2.2 if alpha else 1.3))


def _make(src: Path, dest: Path, size: int) -> None:
    try:
        with Image.open(src) as im:
            im.draft("RGB", (size, size))  # a JPEG decodes at a fraction of its size
            if _cost(im) > DECODE_BUDGET:
                raise InvalidError("image too large to preview")
            icc = im.info.get("icc_profile")
            colour = im.mode
            if im.mode in (
                "P",
                "1",
            ):  # resizing them is nearest-neighbour: smooth first
                im = im.convert("RGBA" if "transparency" in im.info else "RGB")
            im.thumbnail((size, size), Image.Resampling.LANCZOS, reducing_gap=3.0)
            im = ImageOps.exif_transpose(im)  # small now: turn it the way it was held
            if im.mode not in ("RGB", "L"):
                rgba = im.convert("RGBA")  # transparency onto white
                im = Image.new("RGB", rgba.size, "white")
                im.paste(rgba, mask=rgba.getchannel("A"))
            # Keep the colour profile (an iPhone's Display P3) where it still applies
            same = (colour, im.mode) in (("RGB", "RGB"), ("RGBA", "RGB"), ("L", "L"))
            extra = {"icc_profile": icc} if icc and same else {}
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as tmp:
                try:  # no EXIF kept (nor GPS)
                    im.save(tmp, "JPEG", quality=82, progressive=True, **extra)
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
        if not _decoder.acquire(timeout=WAIT):
            raise BusyError()
        try:
            if not dest.is_file():  # made while this one waited
                _make(src, dest, size)
        finally:
            _decoder.release()
    return dest
