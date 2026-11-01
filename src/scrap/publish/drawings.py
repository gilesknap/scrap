"""A page's drawings as its unit holds them (#520; docs/reference/public-site.md,
"Drawings"). The PWA draws each with Excalidraw's exportToSvg, the scene embedded
(exportEmbedScene), and uploads the SVG beside the page's HTML. scrap never trusts
it: for each one it

1. takes the one Excalidraw scene in it (scene.payload), decodes it and cleans it
   (scene.clean): the page's photo in it becomes its 2048-pixel preview, an image
   that is not one of the page's photos goes, its text and links follow the page
   text's rules;
2. runs the SVG through scrap's sanitiser (svg.sanitise), which drops the old scene
   with the <metadata> it is in, then gives what is drawn the same treatment: each
   <image> the preview of the photo it is (or gone), each text scrubbed;
3. puts the cleaned scene back where Excalidraw puts it, so the published SVG is
   both the picture and a drawing excalidraw.com opens.

Photos are matched by content, never by a name the upload gives: an image is one of
the page's photos if its bytes are the photo as stored or that photo's 2048-pixel
preview (Photos)."""

import base64
import binascii
import hashlib
import xml.etree.ElementTree as ET
from collections.abc import Callable

from .. import svg
from ..preview import BusyError, preview, raster
from ..store import InvalidError, NotFoundError, Store, TooLargeError
from . import scene
from .checker import DRAWING_PREFIX, Checked
from .errors import Busy, CheckError
from .links import classify, scrub_text

__all__ = ["MAX_DRAWING", "Photos", "clean_drawing", "page_drawings"]

MAX_DRAWING = 20 * 2**20  # an uploaded drawing's SVG, its photo in it twice
PREVIEW = 2048
IMAGES = ("image", "feImage")


class Photos:
    """What an embedded image is on this page: the bytes of its photo's 2048-pixel
    preview if it is one of the page's photos (stored, or that preview), else None.
    Previews are made once per publish, and only as far as a match needs."""

    def __init__(self, store: Store, on_page: set[str]) -> None:
        self.store = store
        self.shas: list[str] = []
        for sha in sorted(on_page):
            try:
                _, mime = store.blob(sha)
            except NotFoundError:
                continue
            if raster(mime):
                self.shas.append(sha)
        self.previews: dict[str, bytes] = {}  # by the photo's sha
        self.by_preview: dict[str, str] = {}  # a preview's sha256: its photo's sha

    def _preview(self, sha: str) -> bytes:
        if sha not in self.previews:
            try:
                made = preview(self.store, sha, PREVIEW).read_bytes()
            except BusyError:
                raise Busy() from None
            except InvalidError:
                made = b""
            self.previews[sha] = made
            if made:
                self.by_preview[hashlib.sha256(made).hexdigest()] = sha
        return self.previews[sha]

    def __call__(self, data: bytes) -> bytes | None:
        digest = hashlib.sha256(data).hexdigest()
        if digest in self.shas:  # the photo as stored: never published
            return self._preview(digest) or None
        if digest in self.by_preview:
            return self.previews[self.by_preview[digest]]
        for sha in self.shas:
            if sha not in self.previews and self._preview(sha) == data:
                return data
        return None


def _refuse(why: str) -> CheckError:
    return CheckError(f"Not published: a drawing {why}.", "bad_drawing")


def _drawn(
    root: ET.Element,
    images: Callable[[bytes], bytes | None],
    scrub: Callable[[str], str],
    ids: dict[str, str],
) -> None:
    """The SVG's drawing cleaned as its scene was: each embedded image the preview
    of its photo (or gone), each text scrubbed, image ids renamed as the scene's."""
    stack = [root]
    while stack:
        el = stack.pop()
        local = el.tag.rpartition("}")[2]
        for key in ("id", "href"):
            value = el.get(key)
            if value and value.lstrip("#").startswith("image-"):
                for old, new in ids.items():
                    value = value.replace(old, new)
                el.set(key, value)
        if local != "style":
            el.text = scrub(el.text) if el.text else el.text
        for child in list(el):
            child.tail = scrub(child.tail) if child.tail else child.tail
            if child.tag.rpartition("}")[2] in IMAGES:
                m = scene.DATA_URL.fullmatch(child.get("href") or "")
                made = None
                if m is not None:
                    try:
                        made = images(base64.b64decode(m[1], validate=True))
                    except binascii.Error:
                        made = None
                if made is None:
                    el.remove(child)
                    continue
                child.set("href", "data:image/jpeg;base64,"
                          + base64.b64encode(made).decode("ascii"))  # fmt: skip
            stack.append(child)


def clean_drawing(
    text: str,
    images: Callable[[bytes], bytes | None],
    scrub: Callable[[str], str],
    link: Callable[[str], str | None],
) -> bytes:
    """A drawing's SVG as published (see the module docstring); CheckError
    (bad_drawing, or file_too_large) if it cannot be."""
    data = text.encode("utf-8")
    if len(data) > MAX_DRAWING:
        raise CheckError(
            f"Not published: a drawing is over {MAX_DRAWING // 2**20} MiB.",
            "file_too_large",
        )
    found = scene.decode(scene.payload(text))
    cleaned, ids = scene.clean(found, images, scrub, link)
    try:
        safe = svg.sanitise(data, MAX_DRAWING)
        root = svg.parse(safe, svg.GROWTH * MAX_DRAWING)
    except (InvalidError, TooLargeError) as e:
        raise _refuse(f"cannot be made safe ({e})") from None
    _drawn(root, images, scrub, ids)
    out = svg.serialise(root)
    start = out.index(">") + 1  # the root's start tag (its values are escaped)
    out = out[:start] + scene.metadata(scene.encode(cleaned)) + out[start:]
    made = out.encode("utf-8")
    if len(made) > MAX_DRAWING:
        raise CheckError(
            f"Not published: a drawing is over {MAX_DRAWING // 2**20} MiB.",
            "file_too_large",
        )
    return made


def _link(
    site: str | None, is_public: Callable[[str], bool]
) -> Callable[[str], str | None]:
    """A drawing element's link as published: by the page's link rules, a web or
    mailto link as it is, a public page's at its address on the site, else none."""

    def link(href: str) -> str | None:
        try:
            kind, found = classify(href)
        except ValueError:
            return None
        if kind in ("web", "mailto"):
            return href
        if kind == "page" and site and is_public(found):
            return f"{site}/p/{found}"
        return None

    return link


def page_drawings(
    store: Store,
    checked: Checked,
    uploads: dict[str, str],
    ours: frozenset[str],
    on_page: set[str],
    is_public: Callable[[str], bool],
    site: str | None,
) -> dict[str, bytes]:
    """Each drawing the checked page shows, by its id, as published: it must be one
    of the page's (ours) and uploaded, and nothing else uploaded; an Open
    in Excalidraw link only for a drawing shown, and only with an https site."""
    keys = list(dict.fromkeys(
        sha.removeprefix(DRAWING_PREFIX) for sha, _ in checked.blobs
        if sha.startswith(DRAWING_PREFIX)
    ))  # fmt: skip
    for key in keys:
        if key not in ours:
            raise CheckError(
                "Not published: a placeholder names a drawing that is not on the page.",
                "bad_placeholder",
            )
        if key not in uploads:
            raise _refuse("on the page was not sent with it")
    if set(uploads) - set(keys):
        raise _refuse("was sent that the page does not show")
    for key in checked.opens:
        if key not in keys:
            raise CheckError(
                "Not published: an Open in Excalidraw link names a drawing the page"
                " does not show.",
                "bad_placeholder",
            )
        if not (site or "").startswith("https://"):
            raise CheckError(
                "Not published: Open in Excalidraw needs the site's https address"
                " (SCRAP_PUBLISH_SITE).",
                "bad_placeholder",
            )
    if not keys:
        return {}
    photos = Photos(store, on_page)
    link = _link(site, is_public)
    return {k: clean_drawing(uploads[k], photos, scrub_text, link) for k in keys}
