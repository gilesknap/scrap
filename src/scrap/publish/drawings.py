"""A page's drawings as its unit holds them (#520; docs/reference/public-site.md,
"Drawings"). The PWA draws each with Excalidraw's exportToSvg, the scene embedded
(exportEmbedScene), and uploads the SVG beside the page's HTML. scrap never trusts
it: for each one it

1. takes the one Excalidraw scene in it (scene.payload: the root's one <metadata>,
   holding Excalidraw's marker comments; no CDATA anywhere), decodes it and cleans it
   (scene.clean): no image in it, its text and links by the page text's rules;
2. runs the SVG through scrap's sanitiser (svg.sanitise), which drops the old scene
   with the <metadata> it is in, then gives what is drawn the same treatment: no
   <image> and no image symbol, each text and attribute value scrubbed, and an
   inlined font only a font;
3. puts the cleaned scene back where Excalidraw puts it, so the published SVG is
   both the picture and a drawing excalidraw.com opens.

A drawing replaces its photo, as the app's Drawing tab shows it (#524): the PWA sends
it without the photo, and any image an upload has (the photo under it, as 1.3.1's
PWA drew it, or any other) goes, from the picture and the scene."""

import base64
import binascii
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable

from .. import svg
from ..store import InvalidError, TooLargeError
from . import scene
from .checker import DRAWING_PREFIX, Checked
from .errors import CheckError
from .links import classify, scrub_text

__all__ = ["MAX_DRAWING", "clean_drawing", "page_drawings"]

# An uploaded drawing's SVG (an older PWA's had its photo in it twice, which goes)
MAX_DRAWING = 20 * 2**20
IMAGES = ("image", "feImage")
# A font Excalidraw inlines in the SVG's <style>: url(data:font/woff2;base64,...), as
# svg.KEPT keeps it (with any parameters); any other data: in a <style> is refused
DATA = re.compile(r"data:", re.IGNORECASE)
FONT_DATA = re.compile(
    r"url\(\s*['\"]?data:[\w.+/-]*(?:;(?!base64,)[\w=.+-]*)*;base64,([A-Za-z0-9+/=]*)",
    re.IGNORECASE | re.ASCII,
)
FONT_MAGIC = (b"wOF2", b"wOFF")  # WOFF2 and WOFF: their header says their length


def _refuse(why: str) -> CheckError:
    return CheckError(f"Not published: a drawing {why}.", "bad_drawing")


def _an_image(el: ET.Element) -> bool:
    """Whether an element is an image, or Excalidraw's symbol of one or a use of it
    (an id, or a #fragment href, starting image-)."""
    if el.tag.rpartition("}")[2] in IMAGES:
        return True
    return any(
        (el.get(key) or "").removeprefix("#").startswith("image-")
        for key in ("id", "href")
    )


def _fonts(css: str, scrub: Callable[[str], str]) -> None:
    """Refuses a <style> holding embedded data that is not a whole WOFF2 or WOFF font
    (Excalidraw inlines its fonts as data:font/woff2; the header's length must be the
    data's, so nothing rides after it), or an address of scrap's (css is not
    rewritten: it is refused)."""
    found = list(FONT_DATA.finditer(css))
    if len(DATA.findall(css)) != len(found):
        raise _refuse("has embedded data in its style that is not a font")
    for m in found:
        try:
            data = base64.b64decode(m[1], validate=True)
        except binascii.Error:
            raise _refuse("has a font that is not one") from None
        size = int.from_bytes(data[8:12], "big") if len(data) >= 12 else -1
        if not data.startswith(FONT_MAGIC) or size != len(data):
            raise _refuse("has a font that is not one")
    rest = FONT_DATA.sub("", css)
    if scrub(rest) != rest:
        raise _refuse("has an address of scrap's in its style")


def _drawn(root: ET.Element, scrub: Callable[[str], str]) -> None:
    """The SVG's drawing cleaned as its scene was: no image (nor its symbol, nor a
    use of one), each text and attribute value scrubbed."""
    stack = [root]
    while stack:
        el = stack.pop()
        local = el.tag.rpartition("}")[2]
        for key, value in el.attrib.items():  # no address of scrap's in any value
            el.set(key, scene.words(value, scrub))
        if local == "style":
            _fonts(el.text or "", scrub)
        elif el.text:
            el.text = scene.words(el.text, scrub)
        for child in list(el):
            child.tail = scene.words(child.tail, scrub) if child.tail else child.tail
            if _an_image(child):
                el.remove(child)
                continue
            stack.append(child)


def clean_drawing(
    text: str,
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
    if "<![CDATA[" in text:  # Excalidraw writes none; text in it would go out as is
        raise _refuse("has a CDATA section")
    try:
        marked = svg.parse(data, MAX_DRAWING, comments=True)
        found = scene.decode(scene.payload(marked))
        cleaned = scene.clean(found, scrub, link)
        safe = svg.sanitise(data, MAX_DRAWING)
        root = svg.parse(safe, svg.GROWTH * MAX_DRAWING)
        _drawn(root, scrub)
    except (InvalidError, TooLargeError) as e:
        raise _refuse(f"cannot be made safe ({e})") from None
    except RecursionError:
        raise _refuse("is nested too deeply") from None
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
    checked: Checked,
    uploads: dict[str, str],
    ours: frozenset[str],
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
        if not (site or "").lower().startswith("https://"):
            raise CheckError(
                "Not published: Open in Excalidraw needs the site's https address"
                " (SCRAP_PUBLISH_SITE).",
                "bad_placeholder",
            )
    link = _link(site, is_public)
    return {k: clean_drawing(uploads[k], scrub_text, link) for k in keys}
