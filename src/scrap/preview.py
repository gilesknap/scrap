"""JPEG previews of stored photos, made on first request and kept as a cache.

The cache (``cache/previews`` in the data folder) is never backed up: any of it can be
deleted and is made again. Originals are never changed.

Memory: scrap runs in a 1 GB container, and decoding a photo needs all its pixels in
memory at once. So a photo is shrunk straight after decoding, before anything else
copies it; a JPEG is even decoded at 1/2 to 1/8 scale. Photos whose decode would need
more than DECODE_BUDGET are refused (the app shows the original instead), and one
photo is decoded at a time.
"""

import io
import math
import os
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from .claude import backend
from .store import InvalidError, Store
from .svg import is_svg

__all__ = [
    "SIZES",
    "BusyError",
    "cached",
    "claude_jpeg",
    "claude_size",
    "for_claude",
    "own",
    "preview",
    "raster",
]

SIZES = (480, 2048)  # longest side: lists, and the page and viewer
# Bytes one decode may take, as estimated by _cost: about 50 MP for a HEIC (an iPhone's
# 48 MP fits), 80 MP for a PNG, 47 MP with transparency; a JPEG is decoded shrunk, so
# even 120 MP fits. Measured peak RSS over the process's own: 48 MP HEIC 330 MB, 12 MP
# HEIC 90 MB, 40 MP PNG 200 MB (with transparency 355 MB), 100 MP PNG 470 MB (refused
# now), 120 MP JPEG 60 MB, 30 MP WebP 460 MB (so one over 26 MP is refused).
DECODE_BUDGET = 400 * 2**20
CLAUDE_EDGE, CLAUDE_TOKENS = 2048, 4784  # the high-resolution image cap
CLI_EDGE = 2000  # claude -p rescales a longer edge, so none is sent (ADR 0021)
WAIT = 20  # seconds a request waits for the decoder before a 503
Image.MAX_IMAGE_PIXELS = 200_000_000  # Pillow's own bomb check: far past the budget
register_heif_opener()  # iPhone HEIC photos
_decoder = threading.Lock()  # one decode at a time: two big ones would not fit


def raster(mime: str) -> bool:
    """Whether a stored type is an image Pillow decodes here: any image/* but SVG,
    which is markup (#480): it is its own preview (own) and goes to Claude as text."""
    return mime.startswith("image/") and not is_svg(mime)


class BusyError(Exception):
    """Another preview is being made: try again shortly."""


def _cost(im: Image.Image) -> int:
    """Bytes decoding im is expected to take at its peak (from what it decodes to, not
    its size on disk), as measured: a pixel of a colour image takes 4 bytes in Pillow,
    and shrinking one with transparency makes premultiplied copies."""
    pixels = im.width * im.height
    if im.format == "HEIF":
        return pixels * 8  # libheif's YCbCr planes as well as the RGB
    if im.format == "WEBP":
        return pixels * 16  # measured ~15 bytes a pixel: 3x what the rest would say
    alpha = "A" in im.getbands() or "transparency" in im.info
    if len(im.getbands()) > 1 or im.mode in ("P", "1"):
        store = 4
    else:
        store = 2 if im.mode.startswith("I;16") else 4 if im.mode in ("I", "F") else 1
    return int(pixels * store * (2.2 if alpha else 1.3))


def _decode(src: Path, size: int) -> tuple[Image.Image, dict]:
    """A stored image decoded within the budget, upright, flattened to RGB or L and
    at most size pixels a side; with the save options that keep its colour profile."""
    try:
        with Image.open(src) as opened:
            im = opened
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
            if im is opened:  # still the file's: it is closed on leaving this block
                im = im.copy()
            return im, {"icc_profile": icc} if icc and same else {}
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,  # if warnings are errors
        OSError,
        ValueError,
    ):
        raise InvalidError("cannot preview this file") from None


def _make(src: Path, dest: Path, size: int) -> None:
    im, extra = _decode(src, size)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as tmp:
        try:  # no EXIF kept (nor GPS)
            im.save(tmp, "JPEG", quality=82, progressive=True, **extra)
            tmp.close()
            os.replace(tmp.name, dest)
        except BaseException:
            os.unlink(tmp.name)
            raise


def claude_size(width: int, height: int) -> tuple[int, int]:
    """The largest size, never above width x height, with a long edge of at most
    CLAUDE_EDGE pixels (CLI_EDGE on the cli backend) and at most CLAUDE_TOKENS image
    tokens (one per 28 x 28 tile)."""
    long = min(max(width, height), CLI_EDGE if backend() == "cli" else CLAUDE_EDGE)
    while True:
        scale = long / max(width, height)
        w, h = max(1, round(width * scale)), max(1, round(height * scale))
        if math.ceil(w / 28) * math.ceil(h / 28) <= CLAUDE_TOKENS:
            return w, h
        long -= 1


def for_claude(store: Store, sha: str) -> tuple[bytes, int, int]:
    """A stored photo as the JPEG sent to Claude (upright, HEIC converted, sized by
    claude_size) and its width and height. Waits for the decoder."""
    src, mime = store.blob(sha)
    if not raster(mime):
        raise InvalidError("not an image" if not is_svg(mime) else "an SVG is text")
    return claude_jpeg(src)


def claude_jpeg(src: Path) -> tuple[bytes, int, int]:
    """An image file as the JPEG sent to Claude, and its width and height."""
    with _decoder:
        im, extra = _decode(src, CLAUDE_EDGE)
        size = claude_size(*im.size)
        if size != im.size:
            im = im.resize(size, Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=85, **extra)
    return out.getvalue(), *size


def _paths(store: Store, sha: str, size: int) -> tuple[Path, Path]:
    """The original and its preview's place in the cache, after checking both."""
    if size not in SIZES:
        raise InvalidError(f"size must be one of {SIZES}")
    src, mime = store.blob(sha)  # checks sha is a SHA-256 we hold
    if not raster(mime):
        raise InvalidError("not an image" if not is_svg(mime) else "an SVG is its own")
    return src, store.dir / "cache" / "previews" / str(size) / sha[:2] / f"{sha}.jpg"


def own(store: Store, sha: str, size: int) -> Path | None:
    """A stored SVG itself, if sha is one (None if not): the browser scales it to any
    size, so it is its own preview, with no rasteriser (#480). It was sanitised on
    upload (svg.sanitise) and is served with BLOB_HEADERS as any blob is."""
    if size not in SIZES:
        raise InvalidError(f"size must be one of {SIZES}")
    src, mime = store.blob(sha)
    return src if is_svg(mime) else None


def cached(store: Store, sha: str, size: int) -> Path | None:
    """The preview if it is already made (quick: no decoding, no waiting)."""
    dest = _paths(store, sha, size)[1]
    return dest if dest.is_file() else None


def preview(store: Store, sha: str, size: int) -> Path:
    """The path of a JPEG preview of a stored image, at most size pixels a side."""
    src, dest = _paths(store, sha, size)
    if not dest.is_file():
        if not _decoder.acquire(timeout=WAIT):
            raise BusyError()
        try:
            if not dest.is_file():  # made while this one waited
                _make(src, dest, size)
        finally:
            _decoder.release()
    return dest
