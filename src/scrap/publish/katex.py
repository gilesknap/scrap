"""What KaTeX 0.16.47's markup may hold in a published page (docs/reference/
public-site.md, "The HTML scrap accepts" and "KaTeX's markup"): the MathML and SVG
elements, their attributes, and the inline style declarations, derived from every
``setAttribute(...)`` and ``.style.<property> =`` in ``katex.mjs`` and checked
against tests/data/katex_corpus.json. A new KaTeX version means deriving them again.

The ``katex`` gate is visual hygiene, not a security boundary: the CSP is."""

import re

__all__ = [
    "HTML",
    "KATEX_STYLED",
    "MATHML",
    "MATHML_ATTRS",
    "MATHML_ELEMENTS",
    "SVG",
    "SVG_ATTRS",
    "XMLNS",
    "no_url",
    "style_ok",
]

HTML = "http://www.w3.org/1999/xhtml"
MATHML = "http://www.w3.org/1998/Math/MathML"
SVG = "http://www.w3.org/2000/svg"
XMLNS = "{http://www.w3.org/2000/xmlns/}xmlns"  # html5lib's key for xmlns

MATHML_ELEMENTS = frozenset(
    "math semantics annotation mrow mi mn mo mtext mspace msup msub msubsup mfrac"
    " msqrt mroot mover munder munderover mtable mtr mtd mstyle mpadded mphantom"
    " menclose".split()
)
SVG_ELEMENTS = frozenset({"svg", "path", "line"})
MATHML_ATTRS = frozenset(
    "display encoding accent accentunder columnalign columnlines columnspacing"
    " rowlines rowspacing depth voffset lspace rspace width height displaystyle"
    " scriptlevel mathsize mathvariant mathcolor mathbackground linethickness fence"
    " stretchy separator largeop minsize maxsize linebreak notation".split()
)  # and class: KaTeX's MathNode classes (mtd's mtr-glue, mml-eqn-num)
SVG_ATTRS = {
    "svg": frozenset({"width", "height", "viewBox", "preserveAspectRatio"}),
    "path": frozenset({"d"}),
    "line": frozenset({"x1", "y1", "x2", "y2", "stroke-width"}),
}
# Where a style attribute may be, inside KaTeX: (namespace, local name)
KATEX_STYLED = frozenset(
    {(HTML, "span"), (MATHML, "mstyle"), (MATHML, "mpadded"), (SVG, "svg")}
)

_LEN = r"-?(?:[0-9]+|[0-9]*\.[0-9]+)(?:em|ex|px)?"
_COLOUR = (
    r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})"
    r"|rgba?\([0-9.%\s,]*\)"
    r"|[A-Za-z]+"
)
LENGTH = re.compile(_LEN)
COLOUR = re.compile(_COLOUR)
SOLID = re.compile("solid|dashed")
LENGTHS = (
    "height width min-width vertical-align top bottom left margin-left margin-right"
    " margin-top padding-left border-width border-top-width border-right-width"
    " border-bottom-width"
).split()
# property: (its value's pattern, the elements it may be on: None for any styled one)
STYLES: dict[str, tuple[re.Pattern[str], frozenset[str] | None]] = {
    **dict.fromkeys(LENGTHS, (LENGTH, None)),
    "margin": (re.compile(rf"{_LEN}(?:\s+{_LEN})?"), None),
    **dict.fromkeys(("color", "background-color", "border-color"), (COLOUR, None)),
    "border": (
        re.compile(rf"{_LEN}\s+solid(?:\s+(?:{_COLOUR}))?"), frozenset({"mpadded"})
    ),
    **dict.fromkeys(("border-style", "border-right-style"), (SOLID, None)),
    "position": (re.compile("relative"), None),
    "text-shadow": (
        re.compile(rf"{_LEN}\s+{_LEN}\s+{_LEN}"), frozenset({"span", "mstyle"})
    ),
}  # fmt: skip


def no_url(value: str) -> bool:
    """A value with no CSS url( in it (any case, any spaces before the bracket)."""
    return re.search(r"url\s*\(", value, re.IGNORECASE) is None


def style_ok(value: str, local: str) -> str | None:
    """Why a style attribute on element local (inside KaTeX) is refused, else None:
    declarations ``property: value`` separated by ``;``, spaces after ``:`` and a
    trailing ``;`` allowed, each property and value one of STYLES.

    >>> style_ok("height:0.68em;vertical-align:-0.15em;", "span") is None
    True
    >>> style_ok("position: absolute", "span")
    'style position: absolute is not allowed'
    >>> style_ok("text-shadow:1px 1px 1px", "mpadded")
    'style text-shadow is not allowed on mpadded'
    """
    parts = value.split(";")
    if parts and not parts[-1].strip():
        parts.pop()  # the trailing ;
    for part in parts:
        prop, colon, val = part.partition(":")
        prop, val = prop.strip(), val.strip()
        rule = STYLES.get(prop)
        if not colon or rule is None or not rule[0].fullmatch(val):
            return f"style {part.strip() or '(empty)'} is not allowed"
        if rule[1] is not None and local not in rule[1]:
            return f"style {prop} is not allowed on {local}"
    return None
