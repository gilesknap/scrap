"""The check of a page the PWA uploads (docs/reference/public-site.md, "What scrap
sends for a page"): parsed with html5lib, the tree a browser would build, and matched
by (namespace, local name) against an allow-list. Anything not listed refuses the
publish (CheckError, 422): scrap never cleans the HTML.

Placeholders (scrap-blob:, scrap-tag:) are allowed only as the whole value of an
img's src or an a's href. scrap later swaps them in the text as uploaded
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
from .links import ID, classify

__all__ = ["CSP", "KEPT", "RAW_PLACEHOLDER", "Checked", "check"]

CSP = (
    "default-src 'none'; img-src 'self' data:; style-src 'self'; style-src-attr"
    " 'unsafe-inline'; font-src 'self'"
)
STYLESHEETS = ("/assets/page.css", "/assets/katex.css")
KEPT = frozenset(
    "a abbr article aside b blockquote br caption code dd del details div dl dt em"
    " figcaption figure h1 h2 h3 h4 h5 h6 hr i img ins kbd li mark ol p pre q s"
    " section small span strong sub summary sup table tbody td tfoot th thead time tr"
    " u ul".split()
)
HAS_ID = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "a", "li"})
SPAN_DIGITS = re.compile(r"[0-9]{1,3}")
# A placeholder as written in the uploaded text (and swapped there): the scheme, then
# what the publish mode writes after it (a sha, or a URL-encoded tag)
RAW_PLACEHOLDER = re.compile(r"scrap-(?:blob|tag):[^\"'<>\s&]*")
PLACEHOLDER = re.compile(r"scrap-(?:blob|tag):", re.IGNORECASE)
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
    named, with the element naming each (img or a), the tags, the /p/ slugs it links
    to, and whether it has maths."""

    blobs: list[tuple[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    pages: set[str] = field(default_factory=set)
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


class _Walk:
    def __init__(self, is_public: Callable[[str], bool]) -> None:
        self.is_public = is_public
        self.out = Checked()

    def href(self, value: str) -> None:
        try:
            kind, found = classify(value)
        except ValueError as e:
            raise _refuse(str(e)) from None
        if kind == "blob":
            self.blob(found, "a", value)
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
        for key, value in el.attrib.items():
            self.attribute(key, value, ns, local, katex)

    def attribute(self, key: str, value: str, ns: str, local: str, katex: bool) -> None:
        where = f"<{local} {PREFIXES.get(_name(key)[0], '')}{_name(key)[1]}>"
        if key == "href" and ns == HTML and local == "a":
            return self.href(value)
        if key == "src" and ns == HTML and local == "img":
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
        if key == "id":
            return local in HAS_ID and ID.fullmatch(value) is not None
        if key in ("colspan", "rowspan"):
            return local in ("td", "th") and SPAN_DIGITS.fullmatch(value) is not None
        if key == "open":
            return local == "details" and value == ""
        if key == "alt":
            return local == "img"
        if key == "aria-hidden":
            return local == "span" and katex and value == "true"
        return False

    def body(self, root: ET.Element) -> None:
        stack: list[tuple[ET.Element, bool, int]] = [(root, False, 0)]
        while stack:
            el, katex, depth = stack.pop()
            _no_placeholder(el.tail, "the text")
            if el.tag is ET.Comment:  # type: ignore[comparison-overlap]
                _no_placeholder(el.text, "a comment")
                continue
            if depth > MAX_DEPTH:
                raise _refuse("markup nested too deeply")
            if el is not root:
                self.element(el, katex)
            _no_placeholder(el.text, "the text")
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


def _head(head: ET.Element) -> None:
    """The head: only the charset, viewport and fixed CSP metas, the title and the
    page's stylesheets; the CSP and the title must be there."""
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
    raw = Counter(RAW_PLACEHOLDER.findall(text))
    if raw != walk.out.placeholders:
        raise _refuse(
            "a placeholder not written plainly, as the publish mode writes it"
        )
    return walk.out
