"""SVG files (#480): parsed safely, sanitised on upload, and their words read.

An SVG is untrusted markup, whoever sends it (an MCP client's add_svg, the PWA's Add
photo). It is parsed with the standard library's expat with no DOCTYPE at all (so no
entity can be declared, expanded or fetched), and only a root <svg> in the SVG
namespace (or with none, as a hand-written one may) is taken. What is kept is an
allow-list: the elements that draw (shapes, text, paint servers, filters, a few
structural ones), never <script>, <foreignObject>, animation (which can set an href)
or any element of another namespace; no on* attribute; an href only to a fragment of
the same file (#id) or, on an image, a raster data: URL; no ping; in CSS (a <style>,
style and the presentation attributes that take a url) no comment, no @-rule but
@font-face, @media and @keyframes, a url() only to a fragment or an embedded font,
and no image-set(), src() or quoted URL. A DOCTYPE that only names the SVG DTD (as
matplotlib writes) is dropped unread. Served with blobs_api.STRICT_HEADERS as well (a
sandbox, and a CSP that loads nothing from outside the file), and shown in <img>,
where no script runs anyway: this is defence in depth.

The text is what search finds without a model, as a PDF's text layer: the contents of
<title>, <desc> and <text> (its <tspan> and <textPath> too), one line each.
"""

import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from .store.errors import InvalidError, TooLargeError

__all__ = [
    "MAX_SVG",
    "NS",
    "SVG",
    "is_svg",
    "parse",
    "sanitise",
    "serialise",
    "text_of",
]

SVG = "image/svg+xml"
MAX_SVG = 2**20  # bytes, as sent
GROWTH = 2  # how much larger than MAX_SVG one may be once sanitised
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
DATA_IMAGE = re.compile(
    r"data:image/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\t\n\r\f ]*+\Z"
)
DECLARATION = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
# A DOCTYPE naming only an external DTD (matplotlib's, Illustrator's: the SVG 1.1 one),
# with no internal subset ([...]) to declare entities in: stripped, never fetched
PLAIN_DOCTYPE = re.compile(r"<!DOCTYPE\s[^\[\]<>]*+>", re.IGNORECASE)
XML_DECL = re.compile(r"\A\s*+<\?xml[^>]*\?>")
# Every pattern below is ASCII only (CSS whitespace and names are ASCII: a Unicode
# space or letter is part of a URL to a browser), and its repeats possessive (*+),
# so none can backtrack: each runs in linear time on a 1 MiB file
URL = re.compile(r"(?<![a-z0-9_-])url\(", re.IGNORECASE | re.ASCII)  # x-url( is not
# The url()s kept: to a fragment of this file, or an embedded font (as Excalidraw's),
# base64 only (no %-encoding to hide markup in)
KEPT = re.compile(
    r"url\([ \t\n\r\f]*+(['\"]?+)(?:#[\w.-]*+|data:(?:font/[\w.+-]++"
    r"|application/(?:x-)?font-[\w.+-]++)(?:;(?!base64,)[\w=.+-]*+)*+;base64,"
    r"[A-Za-z0-9+/=]*+)\1[ \t\n\r\f]*+\)",
    re.IGNORECASE | re.ASCII,
)
SLASHES = re.compile(r"/{2,}+")
COMMENT = re.compile(r"/\*.*?(?:\*/|\Z)", re.DOTALL)
AT_RULE = re.compile(r"@(?!x-)([\w-]*+)", re.ASCII)
AT_KEPT = ("font-face", "media", "keyframes", "-webkit-keyframes")
STRING = re.compile(r"\"[^\"]*+\"?|'[^']*+'?")
FETCHING = re.compile(
    r"(?<![a-z0-9_-])(?:-webkit-)?(?:image-set|image|cross-fade|element|src)\(",
    re.IGNORECASE | re.ASCII,
)
# The attributes CSS is in, and so url(): style, and the presentation ones that
# take a url (any other attribute is text, kept as it is)
CSS_ATTRS = ("style", "fill", "stroke", "filter", "mask", "clip-path", "marker",
             "marker-start", "marker-mid", "marker-end", "cursor")  # fmt: skip
DROPPED = ("ping", "src")  # attributes that fetch: <a ping>, and no SVG one needs src
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


def parse(data: bytes, limit: int = MAX_SVG) -> ET.Element:
    """The root <svg> of a file, parsed with no DOCTYPE (one naming only an
    external DTD is dropped, unread; one with an internal subset is refused) and so
    no entities; every element put in the SVG namespace if the file uses none.
    UTF-8 only, so the scan for a declaration sees every character. InvalidError
    otherwise; TooLargeError over limit bytes (MAX_SVG, but a public page's drawing,
    which holds its photo, may be larger: publish.drawings)."""
    if len(data) > limit:
        raise TooLargeError(f"an SVG is at most {limit // 1024} KiB")
    try:
        markup = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidError("an SVG must be UTF-8") from None
    markup = XML_DECL.sub("", markup, count=1)  # its encoding= no longer applies
    markup = PLAIN_DOCTYPE.sub("", markup, count=1)
    if DECLARATION.search(markup):  # an internal subset, or an entity: refused
        _refuse()
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
    """CSS that fetches nothing, made by one pass (_css_once) after another until a
    pass changes nothing, so no removal can join what is left into a new rule.

    >>> _css('fill: url("#" x); background: url(http://e/l.png); --a: ")')
    'fill: x-url(); background: x-url(); --a: ")'
    >>> print(_css("fill:url( '#g' ); b: image-set('https://e/x' 1x)"))
    fill:url( '#g' ); b: x-none("" 1x)
    >>> print(_css('/*"*/@imp@import;ort "http:///e/x.css";/*"*/'))
    @x-imp@x-import;ort "";
    """
    for _ in range(50):
        once = _css_once(value)
        if once == value:
            return value
        value = once
    return ""  # never settled: none of it


def _css_once(value: str) -> str:
    """One pass: no comment (which could pair quotes wrongly), no backslash (so no
    escape can spell a name out), no "//"; every @-rule but AT_KEPT made unknown
    (@x-import: ignored, nothing fetched); every url( but KEPT (a #fragment, an
    embedded font) dropped with its argument, each looked at on its own (x-url(): an
    unknown function); then no quoted string holding ":" or "/" (a URL), and no
    image-set(), image(), cross-fade(), element() or src()."""
    value = COMMENT.sub("", value).replace("\\", "")
    kept: list[str] = []
    out, at = [], 0
    while (m := URL.search(value, at)) is not None:
        out.append(value[at : m.start()])
        if keep := KEPT.match(value, m.start()):
            out.append(f"\x00{len(kept)}\x00")  # set aside: its base64 has "//"
            kept.append(keep[0])
            at = keep.end()
        else:  # dropped with its argument, to the next ")" (or the end)
            out.append("x-url()")
            close = value.find(")", m.end())
            at = len(value) if close == -1 else close + 1
    value = "".join(out) + value[at:]
    value = AT_RULE.sub(
        lambda m: m[0] if m[1].lower() in AT_KEPT else f"@x-{m[1]}",
        SLASHES.sub("/", value),  # a run at once: halving it pass by pass is slow
    )

    def string(m: re.Match[str]) -> str:
        return '""' if ":" in m[0] or "/" in m[0] else m[0]

    value = FETCHING.sub("x-none(", STRING.sub(string, value))
    return re.sub("\x00(\\d+)\x00", lambda m: kept[int(m[1])], value)


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
        low = (local or "").lower()  # names are compared in any case: Fill, HREF
        if local is None or low.startswith("on") or low in DROPPED:
            continue  # another namespace's (inkscape:...), or an event handler
        if low == "href":
            if _href(value, tag):
                attrs["href"] = value
            continue
        if "javascript:" in SCHEME.sub("", value).lower():
            continue
        attrs[local] = _css(value) if low in CSS_ATTRS else value
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


def serialise(root: ET.Element) -> str:
    """A parsed (and cleaned) SVG's root as markup, with the SVG namespace on it."""
    parts: list[str] = []
    _write(root, parts, f' xmlns="{NS}"')
    return "".join(parts)


def sanitise(data: bytes, limit: int = MAX_SVG) -> bytes:
    """An SVG file made safe to store and show (see the module docstring), as UTF-8;
    InvalidError if it is not an SVG or declares a DOCTYPE, TooLargeError if it is
    over limit (MAX_SVG unless said)."""
    root = parse(data, limit)
    _clean(root, 0)
    out = serialise(root).encode()
    # The cap is on what is sent (parse). Written out, a file can grow a little
    # (<g/> becomes <g></g>, url(x) x-url()), never by much: twice is room enough
    if len(out) > GROWTH * limit:
        raise TooLargeError(f"an SVG is at most {limit // 1024} KiB")
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
