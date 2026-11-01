"""The check of a page the PWA uploads (docs/reference/public-site.md, "What scrap
sends for a page"): parsed with html5lib, the tree a browser would build, and matched
by (namespace, local name) against an allow-list. Anything not listed refuses the
publish (CheckError, 422): scrap never cleans the HTML.

Placeholders (scrap-blob:, scrap-tag:, scrap-drawing:, scrap-diagram:) are allowed only
as the whole
value of an img's src or an a's href. scrap later swaps them in the text as uploaded
(rewrite.swap), so the check also makes sure each one is written there plainly: the
same placeholders, as many times, as the tree holds."""

import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

import html5lib
from html5lib import treebuilders

from .errors import CheckError
from .katex import (
    HTML,
    KATEX_STYLED,
    MATHML,
    MATHML_ATTRS,
    MATHML_ELEMENTS,
    SVG,
    SVG_ATTRS,
    SVG_ELEMENTS,
    XMLNS,
    no_url,
    style_ok,
)
from .links import DIAGRAM, DRAWING, EXCALIDRAW, ID, classify, private_text

__all__ = ["CSP", "DIAGRAM_PREFIX", "DRAWING_PREFIX", "KEPT", "PREFS_SRC",
           "RAW_PLACEHOLDER", "Checked", "check"]  # fmt: skip

# The page's own CSP: the site's own scripts only, and the one a page names is
# /assets/prefs.js (#519), the theme and width switches
CSP = (
    "default-src 'none'; img-src 'self' data:; style-src 'self'; style-src-attr"
    " 'unsafe-inline'; font-src 'self'; script-src 'self'"
)
# The one script a page may have, in its head: <script src="/assets/prefs.js" defer>
# (or async), and blocking="render" if it likes; no other attribute and no text
PREFS_SRC = "/assets/prefs.js"
DRAWING_PREFIX = "drawing:"  # a drawing's key in Checked.blobs, beside the shas
DIAGRAM_PREFIX = "diagram:"  # a diagram's image there (#525): diagram:<n>-<theme>
STYLESHEETS = ("/assets/page.css", "/assets/katex.css")
# The site's icons (#527): exactly these two links, each once
ICON_LINKS = (
    {"rel": "icon", "href": "/assets/icon.svg", "type": "image/svg+xml"},
    {"rel": "apple-touch-icon", "href": "/assets/icon-192.png"},
)
KEPT = frozenset(
    "a abbr article aside b blockquote br caption code dd del details div dl dt em"
    " figcaption figure h1 h2 h3 h4 h5 h6 hr i img ins kbd li mark ol p pre q s"
    " section small span strong sub summary sup table tbody td tfoot th thead time tr"
    " u ul input label".split()
)  # (input and label only as a photo's tabs: _Walk.attributes)
HAS_ID = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "a", "li"})
SPAN_DIGITS = re.compile(r"[0-9]{1,3}")
# A placeholder as written in the uploaded text (and swapped there): the scheme, then
# what the publish mode writes after it (a sha, or a URL-encoded tag, which may hold
# ' as encodeURIComponent leaves it), up to the double quote the publish mode closes
# the attribute with. (One in single quotes takes the quote too, and is refused.)
RAW_PLACEHOLDER = re.compile(
    r"scrap-(?:blob|tag|drawing|excalidraw|diagram):[^\"<>\s&]*"
)
PLACEHOLDER = re.compile(
    r"scrap-(?:blob|tag|drawing|excalidraw|diagram):", re.IGNORECASE
)
# A photo's Photo | Drawing tabs (#520), in CSS alone: two radio inputs and their
# labels, named and labelled pair-<n>[-photo|-drawing], in a div role="radiogroup"
PAIR = re.compile(r"pair-[0-9]{1,3}(?:-photo|-drawing)?")
NEW_TAB = {"target": "_blank", "rel": "noopener noreferrer"}  # Open in Excalidraw
# A task's box (#539): an empty span, its class and its label, by its state
TASKBOX = {"taskbox": "To do", "taskbox done": "Done"}
# html5lib's parse errors for markup the contract refuses outright
REFUSED_ERRORS = {
    "duplicate-attribute": "an attribute given twice",
    "expected-tag-name-but-got-question-mark": "a processing instruction",
    "expected-dashes-or-doctype": "a CDATA section or other <! markup",
}
MAX_DEPTH = 256  # elements nested deeper refuse the publish
PREFIXES = {  # an attribute's namespace as written, in a refusal's message
    "http://www.w3.org/1999/xlink": "xlink:",
    "http://www.w3.org/XML/1998/namespace": "xml:",
    "http://www.w3.org/2000/xmlns/": "",
}


@dataclass
class Checked:
    """What a page that passed holds: the stored files it names, in the order first
    named, with the element naming each (img or a; a drawing's key as
    DRAWING_PREFIX + key, #520; a diagram's image as DIAGRAM_PREFIX + <n>-<theme>,
    #525), the tags, the /p/ slugs it links to, and whether it
    has maths."""

    blobs: list[tuple[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    pages: set[str] = field(default_factory=set)
    opens: list[str] = field(default_factory=list)  # drawings' Open in Excalidraw
    placeholders: Counter[str] = field(default_factory=Counter)
    maths: bool = False


def _refuse(why: str) -> CheckError:
    return CheckError(f"Not published: {why}.")


def _name(tag: str) -> tuple[str, str]:
    """An element's (namespace, local name)."""
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    return "", tag


def _classes(el: ET.Element) -> list[str]:
    return (el.get("class") or "").split()


def _no_placeholder(text: str | None, where: str) -> None:
    if text and PLACEHOLDER.search(text):
        raise _refuse(f"a placeholder in {where}")


def _plain(text: str | None, where: str) -> None:
    """Text in the body: no placeholder, and no private address of scrap's (its own
    hosts, /api/blobs/), which the PWA writes as "a private link"."""
    _no_placeholder(text, where)
    if text and (found := private_text(text)):
        raise _refuse(f"a private address of scrap's in {where} ({found})")


class _Walk:
    def __init__(self, is_public: Callable[[str], bool]) -> None:
        self.is_public = is_public
        self.out = Checked()
        self.inputs: set[str] = set()  # the tabs' radio ids
        self.labels: list[str] = []  # what their labels are for

    def href(self, value: str) -> None:
        try:
            kind, found = classify(value)
        except ValueError as e:
            raise _refuse(str(e)) from None
        if kind == "blob":
            self.blob(found, "a", value)
        elif kind == "drawing":
            self.blob(DRAWING_PREFIX + found, "a", value)
        elif kind == "excalidraw":
            self.out.opens.append(found)
            self.out.placeholders[value] += 1
        elif kind == "tag":
            self.out.tags.append(found)
            self.out.placeholders[value] += 1
        elif kind == "page":
            if not self.is_public(found):
                raise _refuse(f"a link to a page that is not public: /p/{found}")
            self.out.pages.add(found)
        elif PLACEHOLDER.search(value):
            raise _refuse("a placeholder inside a link")

    def blob(self, sha: str, element: str, value: str) -> None:
        if (sha, element) not in self.out.blobs:
            self.out.blobs.append((sha, element))
        self.out.placeholders[value] += 1

    def attributes(self, el: ET.Element, ns: str, local: str, katex: bool) -> None:
        href = el.get("href") or ""
        if ns == HTML and local == "a" and EXCALIDRAW.fullmatch(href):
            if {k: el.get(k) for k in NEW_TAB} != NEW_TAB:
                raise _refuse("an Open in Excalidraw link not opening a new tab")
        diagram = DIAGRAM.fullmatch(el.get("src") or "")
        if ns == HTML and local == "img" and diagram:
            # a diagram's image (#525): classed as its theme, which page.css shows
            if el.get("class") != diagram[2]:
                raise _refuse("a diagram's image not classed as its theme")
        if ns == HTML and local == "input":
            if el.get("type") != "radio" or not PAIR.fullmatch(el.get("id") or ""):
                raise _refuse("an <input> other than a photo's tabs")
            self.inputs.add(el.get("id") or "")
        if ns == HTML and local == "span" and _taskbox(el):
            return
        if ns == HTML and local == "label":
            if not PAIR.fullmatch(el.get("for") or ""):
                raise _refuse("a <label> other than a photo's tabs")
            self.labels.append(el.get("for") or "")
        for key, value in el.attrib.items():
            if key == "download" and ns == HTML and local == "a":
                # only a drawing's download link (#520), as the publish mode writes it
                if value != "" or not DRAWING.fullmatch(href):
                    raise _refuse("<a download> other than a drawing's")
                continue
            if key in NEW_TAB and ns == HTML and local == "a":
                if not EXCALIDRAW.fullmatch(href) or value != NEW_TAB[key]:
                    raise _refuse(f"<a {key}> other than Open in Excalidraw's")
                continue
            self.attribute(key, value, ns, local, katex)

    def attribute(self, key: str, value: str, ns: str, local: str, katex: bool) -> None:
        where = f"<{local} {PREFIXES.get(_name(key)[0], '')}{_name(key)[1]}>"
        if key == "href" and ns == HTML and local == "a":
            return self.href(value)
        if key == "src" and ns == HTML and local == "img":
            if m := DRAWING.fullmatch(value):
                return self.blob(DRAWING_PREFIX + m[1], "img", value)
            if m := DIAGRAM.fullmatch(value):
                return self.blob(f"{DIAGRAM_PREFIX}{m[1]}-{m[2]}", "img", value)
            m = re.fullmatch(r"scrap-blob:([0-9a-f]{64})", value)
            if not m:
                raise _refuse("an image that is not a placeholder (scrap-blob:)")
            return self.blob(m[1], "img", value)
        _no_placeholder(value, where)
        if key == XMLNS:
            want = {(MATHML, "math"): MATHML, (SVG, "svg"): SVG}.get((ns, local))
            if want is None or value != want:
                raise _refuse(f"{where} is not allowed")
            return None
        if key == "style":
            if not katex or (ns, local) not in KATEX_STYLED:
                raise _refuse(f"a style attribute outside KaTeX's markup ({where})")
            if why := style_ok(value, local):
                raise _refuse(why)
            return None
        if ns == HTML and self.html_attribute(key, value, local, katex):
            return None
        if ns == MATHML and (key in MATHML_ATTRS or key == "class") and no_url(value):
            return None
        if ns == SVG and key in SVG_ATTRS[local] and no_url(value):
            return None
        raise _refuse(f"{where} is not allowed")

    @staticmethod
    def html_attribute(key: str, value: str, local: str, katex: bool) -> bool:
        if key in ("class", "dir"):
            return True
        if key == "id" and local == "input":
            return PAIR.fullmatch(value) is not None
        if key == "id":
            return local in HAS_ID and ID.fullmatch(value) is not None
        # A photo's tabs (#520): radio inputs (the type was checked with the
        # element), their labels and the group round them
        if key == "type":
            return local == "input" and value == "radio"
        if key == "name":
            return local == "input" and PAIR.fullmatch(value) is not None
        if key == "checked":
            return local == "input" and value == ""
        if key == "for":
            return local == "label" and PAIR.fullmatch(value) is not None
        if key == "role":
            return local == "div" and value == "radiogroup"
        if key == "aria-label" and local in ("input", "div"):
            _plain(value, "an aria-label")
            return True
        if key in ("colspan", "rowspan"):
            return local in ("td", "th") and SPAN_DIGITS.fullmatch(value) is not None
        if key == "open":
            return local == "details" and value == ""
        if key == "alt":  # its text, as body text: no private address of scrap's
            if local == "img":
                _plain(value, "an img's alt")
            return local == "img"
        if key == "aria-hidden":
            return local == "span" and katex and value == "true"
        return False

    def body(self, root: ET.Element) -> None:
        stack: list[tuple[ET.Element, bool, int]] = [(root, False, 0)]
        while stack:
            el, katex, depth = stack.pop()
            _plain(el.tail, "the text")
            if el.tag is ET.Comment:  # type: ignore[comparison-overlap]
                _plain(el.text, "a comment")
                continue
            if depth > MAX_DEPTH:
                raise _refuse("markup nested too deeply")
            if el is not root:
                self.element(el, katex)
            _plain(el.text, "the text")
            ns, local = _name(el.tag)
            inner = katex or (
                ns == HTML and local == "span" and "katex" in _classes(el)
            )
            if inner and not katex:
                self.out.maths = True
            stack.extend((child, inner, depth + 1) for child in reversed(el))

    def element(self, el: ET.Element, katex: bool) -> None:
        ns, local = _name(el.tag)
        if ns == HTML and local in KEPT:
            pass
        elif ns == HTML and katex and local in MATHML_ELEMENTS:
            # KaTeX's MathML inside a text integration point (mi, mo, mn, ms, mtext):
            # a browser, as html5lib, parses it as HTML, an element with no meaning
            # there. It is checked as MathML.
            ns = MATHML
        elif ns == MATHML and katex and local in MATHML_ELEMENTS:
            pass
        elif ns == SVG and katex and local in SVG_ELEMENTS:
            pass
        else:
            what = {MATHML: "MathML ", SVG: "SVG "}.get(ns, "")
            raise _refuse(f"{what}<{local}> is not allowed here")
        self.attributes(el, ns, local, katex)


def _taskbox(el: ET.Element) -> bool:
    """Whether a span is a task's box (#539), which must be exactly as the publish
    mode writes it: <span class="taskbox" role="img" aria-label="To do"> or
    <span class="taskbox done" role="img" aria-label="Done">, empty. A span with
    a role, or classed taskbox, that is not one is refused."""
    cls = el.get("class") or ""
    if "role" not in el.attrib and "taskbox" not in cls.split():
        return False
    want = TASKBOX.get(cls)
    attrs = {"class": cls, "role": "img", "aria-label": want}
    if want is None or dict(el.attrib) != attrs or el.text or len(el):
        raise _refuse("a task's box other than the publish mode's")
    return True


def _prefs_script(el: ET.Element, attrs: dict[str, str]) -> bool:
    """Whether a <script> in the head is the one a page may have (#519): exactly
    src="/assets/prefs.js", with defer or async (not both), blocking="render" if
    given, nothing else, and no text."""
    rest = dict(attrs)
    if rest.pop("src", None) != PREFS_SRC or (el.text or "") or len(el):
        return False
    if rest.get("blocking", "render") != "render":
        return False
    rest.pop("blocking", None)
    return rest in ({"defer": ""}, {"async": ""})


def _head(head: ET.Element) -> None:
    """The head: only the charset, viewport and fixed CSP metas, the title, the
    page's stylesheets, the site's two icon links and its one script (prefs.js);
    the CSP and the title must be there."""
    seen: Counter[str] = Counter()
    if head.attrib:
        raise _refuse("attributes on <head>")
    for el in head:
        _no_placeholder(el.tail, "the head")
        if (el.tail or "").strip():
            raise _refuse("text in the head")
        if el.tag is ET.Comment:  # type: ignore[comparison-overlap]
            _no_placeholder(el.text, "a comment")
            continue
        ns, local = _name(el.tag)
        attrs = dict(el.attrib)
        kind = None
        if ns == HTML and local == "title" and not attrs and not len(el):
            _no_placeholder(el.text, "the title")
            kind = "title"
        elif ns == HTML and local == "meta" and not len(el):
            if (
                attrs == {"charset": attrs.get("charset")}
                and (attrs["charset"] or "").lower() == "utf-8"
            ):
                kind = "charset"
            elif set(attrs) == {"name", "content"} and attrs["name"] == "viewport":
                _no_placeholder(attrs["content"], "the viewport")
                kind = "viewport"
            elif (
                set(attrs) == {"http-equiv", "content"}
                and attrs["http-equiv"].lower() == "content-security-policy"
            ):
                if " ".join(attrs["content"].split()) != CSP:
                    raise _refuse("the page's Content-Security-Policy is not scrap's")
                kind = "csp"
        elif (
            ns == HTML
            and local == "link"
            and set(attrs) == {"rel", "href"}
            and attrs["rel"] == "stylesheet"
            and attrs["href"] in STYLESHEETS
        ):
            kind = attrs["href"]
        elif ns == HTML and local == "link" and not len(el) and attrs in ICON_LINKS:
            kind = attrs["href"]
        elif ns == HTML and local == "script" and _prefs_script(el, attrs):
            kind = "script"
        if kind is None:
            raise _refuse(f"<{local}> is not allowed in the head")
        seen[kind] += 1
        if seen[kind] > 1:
            raise _refuse(f"two of <{local}> in the head")
    if not seen["csp"]:
        raise _refuse("the page has no Content-Security-Policy")
    if not seen["title"]:
        raise _refuse("the page has no title")


def _document(text: str) -> tuple[ET.Element, ET.Element]:
    """The parsed page's head and body, after the document-level checks."""
    if "<![CDATA[" in text or "<?" in text:
        raise _refuse("a CDATA section or processing instruction")
    parser = html5lib.HTMLParser(
        tree=treebuilders.getTreeBuilder("etree", fullTree=True),
        namespaceHTMLElements=True,
    )
    document = parser.parse(text)
    for _, code, _ in parser.errors:
        if code in REFUSED_ERRORS:
            raise _refuse(REFUSED_ERRORS[code])
    top = [e for e in document if e.tag is not ET.Comment]  # type: ignore[comparison-overlap]
    if (
        len(top) != 2
        or top[0].tag != "<!DOCTYPE>"
        or (top[0].text or "").lower() != "html"
        or top[0].get("publicId")
        or top[0].get("systemId")
    ):
        raise _refuse("the page must start <!DOCTYPE html>")
    html = top[1]
    if set(html.attrib) - {"lang", "dir"}:
        raise _refuse("attributes on <html> other than lang and dir")
    parts = [e for e in html if e.tag is not ET.Comment]  # type: ignore[comparison-overlap]
    if [e.tag for e in parts] != [f"{{{HTML}}}head", f"{{{HTML}}}body"]:
        raise _refuse("the page must be a head and a body")
    head, body = parts
    if set(body.attrib) - {"lang", "dir"}:
        raise _refuse("attributes on <body> other than lang and dir")
    for value in (*html.attrib.values(), *body.attrib.values()):
        _no_placeholder(value, "an attribute")
    for el in (*document, *html):  # what is outside the head and body
        _no_placeholder(el.tail, "the text")
        if el.tag is ET.Comment:  # type: ignore[comparison-overlap]
            _no_placeholder(el.text, "a comment")
    _no_placeholder(html.text, "the text")
    _no_placeholder(head.text, "the head")
    return head, body


def check(text: str, is_public: Callable[[str], bool]) -> Checked:
    """Check a page from the publish mode; CheckError (422) saying why it is refused.
    is_public(slug) says whether a /p/<slug> link may stay (that page is public)."""
    head, body = _document(text)
    _head(head)
    walk = _Walk(is_public)
    walk.body(body)
    if gone := [f for f in walk.labels if f not in walk.inputs]:
        raise _refuse(f"a <label> for no tab ({gone[0]})")
    raw = Counter(RAW_PLACEHOLDER.findall(text))
    if raw != walk.out.placeholders:
        raise _refuse(
            "a placeholder not written plainly, as the publish mode writes it"
        )
    return walk.out
