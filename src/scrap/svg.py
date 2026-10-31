"""SVG files (#480): parsed safely, sanitised on upload, and their words read.

An SVG is untrusted markup, whoever sends it (an MCP client's add_svg, the PWA's Add
photo). It is parsed with the standard library's expat with no DOCTYPE at all (so no
entity can be declared, expanded or fetched), and only a root <svg> in the SVG
namespace (or with none, as a hand-written one may) is taken. What is kept is an
allow-list: the elements that draw (shapes, text, paint servers, filters, a few
structural ones), never <script>, <foreignObject>, animation (which can set an href)
or any element of another namespace; no on* attribute; an href only to a fragment of
the same file (#id) or, on an image, a raster data: URL; a url() in an attribute or a
<style> only to a fragment, and no @import. Served with BLOB_HEADERS
(Content-Security-Policy: sandbox, nosniff) as well, and shown in <img>, where no
script runs anyway: this is defence in depth.

The text is what search finds without a model, as a PDF's text layer: the contents of
<title>, <desc> and <text> (its <tspan> and <textPath> too), one line each.
"""

import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from .store.errors import InvalidError, TooLargeError

__all__ = ["MAX_SVG", "SVG", "is_svg", "sanitise", "text_of"]

SVG = "image/svg+xml"
MAX_SVG = 2**20  # bytes, as sent and as stored
MAX_DEPTH = 100  # nested elements: a deeper file is refused, not walked
NS = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
XML = "http://www.w3.org/XML/1998/namespace"
ELEMENTS = frozenset(
    """svg g defs symbol use title desc switch view a
    path rect circle ellipse line polyline polygon text tspan textPath image style
    marker pattern clipPath mask linearGradient radialGradient stop
    filter feBlend feColorMatrix feComponentTransfer feComposite feConvolveMatrix
    feDiffuseLighting feDisplacementMap feDistantLight feDropShadow feFlood feFuncA
    feFuncB feFuncG feFuncR feGaussianBlur feImage feMerge feMergeNode feMorphology
    feOffset fePointLight feSpecularLighting feSpotLight feTile feTurbulence""".split()
)
IMAGES = ("image", "feImage")  # the elements whose href may be a raster data: URL
DATA_IMAGE = re.compile(r"data:image/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]*\Z")
DECLARATION = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
XML_DECL = re.compile(r"\A\s*<\?xml[^>]*\?>")
URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
IMPORT = re.compile(r"@import\b[^;]*;?", re.IGNORECASE)
SCHEME = re.compile(r"[\x00-\x20]+")  # what a browser skips inside "java script:"
WORDS = ("title", "desc", "text")


def is_svg(mime: str) -> bool:
    """Whether a stored type is SVG (a parameter such as charset= aside)."""
    return mime.split(";", 1)[0].strip().lower() == SVG


def _refuse(*_: object) -> None:
    raise InvalidError("an SVG must not have a DOCTYPE or entities")


class _Builder(ET.TreeBuilder):
    """A tree builder that refuses a DOCTYPE (the scan in parse comes first)."""

    def doctype(self, *_: object) -> None:
        _refuse()


def parse(data: bytes) -> ET.Element:
    """The root <svg> of a file, parsed with no DOCTYPE and so no entities; every
    element put in the SVG namespace if the file uses none. UTF-8 only, so the scan
    for a declaration sees every character. InvalidError otherwise."""
    if len(data) > MAX_SVG:
        raise TooLargeError(f"an SVG is at most {MAX_SVG // 1024} KiB")
    try:
        markup = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidError("an SVG must be UTF-8") from None
    if DECLARATION.search(markup):
        _refuse()
    markup = XML_DECL.sub("", markup, count=1)  # its encoding= no longer applies
    parser = ET.XMLParser(target=_Builder())  # comments and PIs are dropped
    try:
        parser.feed(markup)
        root = parser.close()
    except ET.ParseError as error:
        raise InvalidError(f"not well-formed SVG: {error}") from None
    if root.tag == "svg":  # no namespace: a hand-written file, as a browser takes it
        for el in root.iter():
            if isinstance(el.tag, str) and not el.tag.startswith("{"):
                el.tag = f"{{{NS}}}{el.tag}"
    if root.tag != f"{{{NS}}}svg":
        raise InvalidError("not an SVG: the root element must be <svg>")
    return root


def _local(name: str, ns: str) -> str | None:
    """The local name of a tag or attribute in namespace ns ("" for none)."""
    if not ns:
        return None if name.startswith("{") else name
    prefix = f"{{{ns}}}"
    return name[len(prefix) :] if name.startswith(prefix) else None


def _css(value: str) -> str:
    """CSS with every url() not to a fragment of this file made none, and no @import;
    no backslash either, so no escape (u\\72l) can spell either out."""

    def one(m: re.Match[str]) -> str:
        return m[0] if m[2].strip().startswith("#") else "none"

    return URL.sub(one, IMPORT.sub("", value.replace("\\", "")))


def _href(value: str, tag: str) -> bool:
    """Whether an href is kept: to a fragment, or a raster data: URL on an image."""
    v = SCHEME.sub("", value)
    return v.startswith("#") or (tag in IMAGES and bool(DATA_IMAGE.match(value)))


def _clean(el: ET.Element, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise InvalidError(f"an SVG nests at most {MAX_DEPTH} elements deep")
    tag = _local(el.tag, NS) or ""
    attrs = {}
    for name, value in el.attrib.items():
        local = _local(name, "")
        if name == f"{{{XLINK}}}href":
            local = "href"
        elif name in (f"{{{XML}}}space", f"{{{XML}}}lang"):
            attrs[name] = value
            continue
        if local is None or local.lower().startswith("on"):
            continue  # another namespace's (inkscape:...), or an event handler
        if local == "href":
            if _href(value, tag):
                attrs["href"] = value
            continue
        if "javascript:" in SCHEME.sub("", value).lower():
            continue
        css = local == "style" or "(" in value or "\\" in value
        attrs[local] = _css(value) if css else value
    el.attrib.clear()
    el.attrib.update(attrs)
    if tag == "style":
        el.text = _css(el.text or "")
        el[:] = []
    for child in list(el):
        if _local(child.tag, NS) in ELEMENTS:
            _clean(child, depth + 1)
        else:  # its words go too: <script>, <foreignObject>, <set>, <animate>...
            el.remove(child)


def _write(el: ET.Element, out: list[str], extra: str = "") -> None:
    """el as markup (ElementTree's own writer will not leave SVG unprefixed)."""
    tag = _local(el.tag, NS)
    names = {f"{{{XML}}}space": "xml:space", f"{{{XML}}}lang": "xml:lang"}
    attrs = "".join(f" {names.get(k, k)}={quoteattr(v)}" for k, v in el.attrib.items())
    out.append(f"<{tag}{extra}{attrs}>{escape(el.text or '')}")
    for child in el:
        _write(child, out)
        out.append(escape(child.tail or ""))
    out.append(f"</{tag}>")


def sanitise(data: bytes) -> bytes:
    """An SVG file made safe to store and show (see the module docstring), as UTF-8;
    InvalidError if it is not an SVG or declares a DOCTYPE, TooLargeError if it is
    over MAX_SVG."""
    root = parse(data)
    _clean(root, 0)
    parts: list[str] = []
    _write(root, parts, f' xmlns="{NS}"')
    out = "".join(parts).encode()
    if len(out) > MAX_SVG:  # an entity-free file only shrinks, but say so if not
        raise TooLargeError(f"an SVG is at most {MAX_SVG // 1024} KiB")
    return out


def text_of(data: bytes) -> str:
    """The words of an SVG: its <title>, <desc> and <text> contents, one a line (each
    once, in order). An SVG that cannot be parsed has none.

    >>> text_of(b'<svg xmlns="http://www.w3.org/2000/svg"><title>Right angle</title>'
    ...         b'<text>12 <tspan>cm</tspan></text><text>30\\xc2\\xb0</text></svg>')
    'Right angle\\n12 cm\\n30\\xb0'
    """
    try:
        root = parse(data)
    except (InvalidError, TooLargeError):
        return ""
    lines: dict[str, None] = {}
    stack = [root]  # not recursive: a stored file may nest deeper than Python allows
    while stack:
        el = stack.pop()
        if _local(el.tag, NS) in WORDS:  # a <text> is read whole: its tspans with it
            line = " ".join("".join(el.itertext()).split())
            if line:
                lines[line] = None
        else:
            stack.extend(reversed(el))
    return "\n".join(lines)
