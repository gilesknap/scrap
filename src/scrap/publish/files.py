"""A page's images and files as its unit holds them (docs/reference/public-site.md,
"Placeholders and files"): what each ``scrap-blob:<sha>`` becomes, by the stored file,
not the element. An image is never published as its original: a raster image goes out
as its 2048-pixel preview (a JPEG, with no EXIF or GPS: preview._make), an SVG through
the sanitiser again; any other file as stored. Names are new: neither the stored sha
nor the uploaded file name is published."""

import hashlib
from dataclasses import dataclass

from ..preview import BusyError, preview, raster
from ..store import InvalidError, NotFoundError, Store, TooLargeError
from ..svg import is_svg, sanitise
from .errors import CheckError, PublishError

__all__ = ["MAX_FILE", "MAX_FILES", "MAX_UNIT", "Files", "page_files"]

MAX_FILES = 20  # images and files together, on one page
MAX_FILE = 20 * 2**20  # each, as published
MAX_UNIT = 200 * 2**20  # the whole unit, index.html too (the receiver takes 256 MiB)
PREVIEW = 2048
# The types a file-* goes out as (the receiver's list), by the stored type
EXTENSIONS = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/csv": "csv",
    "application/zip": "zip",
    "application/epub+zip": "epub",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
}


@dataclass
class Files:
    """A page's published files: each stored sha's name in the unit, and the bytes
    under each name."""

    names: dict[str, str]
    data: dict[str, bytes]


def extension(mime: str) -> str:
    """The extension a file that is not an image goes out with: from the receiver's
    list, else bin (never html, js, css or svg).

    >>> extension("application/pdf"), extension("text/html")
    ('pdf', 'bin')
    >>> extension("text/plain; charset=utf-8")
    'txt'
    """
    return EXTENSIONS.get(mime.split(";", 1)[0].strip().lower(), "bin")


def _too_big(what: str) -> CheckError:
    return CheckError(
        f"Not published: {what} is over {MAX_FILE // 2**20} MiB.", "file_too_large"
    )


def _image(store: Store, sha: str, mime: str) -> tuple[bytes, str]:
    """An image's published bytes and extension: its preview, or the SVG sanitised."""
    path, _ = store.blob(sha)
    if is_svg(mime):
        try:
            return sanitise(path.read_bytes()), "svg"
        except (InvalidError, TooLargeError) as e:
            raise CheckError(
                f"Not published: an SVG on the page cannot be made safe ({e}).",
                "bad_placeholder",
            ) from None
    try:
        made = preview(store, sha, PREVIEW)
    except BusyError:
        raise PublishError("another preview is being made: try again", "busy") from None
    except InvalidError as e:
        raise CheckError(
            f"Not published: an image on the page has no preview ({e}).",
            "bad_placeholder",
        ) from None
    return made.read_bytes(), "jpg"


def _stored(store: Store, sha: str) -> bytes:
    path, _ = store.blob(sha)
    if path.stat().st_size > MAX_FILE:
        raise _too_big("a file on the page")
    return path.read_bytes()


def page_files(
    store: Store, blobs: list[tuple[str, str]], on_page: set[str], html_bytes: int
) -> Files:
    """The files for blobs ((sha, element) in the order first named, from the check),
    each of which must be on the page (on_page: the stored files its text refers to);
    refused (CheckError) for one that is not, an img naming a file that is not an
    image, and over the caps (counting html_bytes, the page's own HTML, in the
    unit's total)."""
    names: dict[str, str] = {}
    data: dict[str, bytes] = {}
    count = {"img": 0, "file": 0}
    total = html_bytes
    for sha, element in blobs:
        if sha in names:
            continue
        try:
            if sha not in on_page:
                raise NotFoundError(sha)
            _, mime = store.blob(sha)
        except NotFoundError:
            raise CheckError(
                "Not published: a placeholder names a file that is not on the page.",
                "bad_placeholder",
            ) from None
        image = raster(mime) or is_svg(mime)
        if element == "img" and not image:
            raise CheckError(
                "Not published: an image placeholder names a file that is not an"
                " image.",
                "bad_placeholder",
            )
        if len(names) >= MAX_FILES:
            raise CheckError(
                f"Not published: a page publishes at most {MAX_FILES} images and"
                " files.",
                "too_many_files",
            )
        if image:
            content, ext = _image(store, sha, mime)
            kind = "img"
        else:
            content, ext, kind = _stored(store, sha), extension(mime), "file"
        if len(content) > MAX_FILE:
            raise _too_big("an image" if image else "a file on the page")
        total += len(content)
        if total > MAX_UNIT:
            raise CheckError(
                f"Not published: the page and its files are over"
                f" {MAX_UNIT // 2**20} MiB.",
                "unit_too_large",
            )
        count[kind] += 1
        name = f"{kind}-{count[kind]}-{hashlib.sha256(content).hexdigest()[:10]}.{ext}"
        names[sha], data[name] = name, content
    return Files(names, data)
