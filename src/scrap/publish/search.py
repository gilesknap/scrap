"""The site's search index, the ``pagefind`` unit (docs/reference/public-site.md,
"What scrap builds"): built by the pagefind Python package (its pinned binary) from
the kept copies, each indexed as its text with every ``.katex`` element replaced by
the formula's TeX (its annotation), so search finds the TeX rather than KaTeX's glyph
spans. Pagefind's UI files go with it, and scrap-search.js, which starts the UI; its
stylesheet goes to the assets unit, as CSS lives only there."""

import asyncio
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import html5lib
from pagefind.index import PagefindIndex

from .katex import HTML, MATHML

__all__ = ["UI_CSS", "build_index", "index_text"]

UI_CSS = "pagefind-ui.css"  # Pagefind's UI stylesheet, for the assets unit
UNIT_TYPES = (".js", ".mjs", ".json", ".wasm", ".pagefind") + tuple(
    f".pf_{k}" for k in ("meta", "index", "fragment", "filter")
)
# Starts Pagefind's UI in home's search box: an external file, as home's CSP allows
# no inline script
START = b"""// scrap's start-up file for Pagefind's search UI (public-site.md)
window.addEventListener("DOMContentLoaded", () => {
  new PagefindUI({ element: "#search", showImages: false, resetStyles: false });
});
"""
BLOCKS = frozenset(
    "p div li h1 h2 h3 h4 h5 h6 pre blockquote tr td th dt dd figcaption summary"
    " section article aside br".split()
)
TEX = "application/x-tex"


def _tex(el: ET.Element) -> str:
    for a in el.iter(f"{{{MATHML}}}annotation"):
        if a.get("encoding") == TEX:
            return "".join(a.itertext())
    return ""


def index_text(html: bytes | str) -> str:
    """A kept page's text for the index: its body's text, a KaTeX formula as its TeX.

    >>> index_text('<p>Area <span class="katex"><math><semantics><mi>r</mi>'
    ...   '<annotation encoding="application/x-tex">\\\\pi r^2</annotation>'
    ...   '</semantics></math><span class="katex-html">πr2</span></span></p>')
    'Area \\\\pi r^2'
    """
    root = html5lib.parse(html, treebuilder="etree", namespaceHTMLElements=True)
    body = root.find(f"{{{HTML}}}body")
    out: list[str] = []
    stack: list[ET.Element | str] = [body] if body is not None else []
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
            continue
        if item.tag is ET.Comment:  # type: ignore[comparison-overlap]
            out.append(item.tail or "")
            continue
        local = item.tag.rpartition("}")[2]
        gap = " " if local in BLOCKS else ""
        if local == "span" and "katex" in (item.get("class") or "").split():
            stack.append(f"{gap}{item.tail or ''}")
            out.append(f" {_tex(item)} ")
            continue
        stack.append(f"{gap}{item.tail or ''}")
        stack.extend(reversed(list(item)))
        out.append(f"{gap}{item.text or ''}")
    return " ".join("".join(out).split())


async def _build(records: list[tuple[str, str, str]], out: Path) -> None:
    config = {"force_language": "en", "output_path": str(out)}
    async with PagefindIndex(config) as index:  # type: ignore[arg-type]
        for url, title, text in records:
            await index.add_custom_record(
                url=url, content=text, language="en", meta={"title": title}
            )


def build_index(records: list[tuple[str, str, str]]) -> tuple[dict[str, bytes], bytes]:
    """The pagefind unit's files for records ((url, title, text), sorted) and Pagefind's
    UI stylesheet. Runs the pagefind binary; call it from a thread with no event loop
    (a sync route's, or reconcile's)."""
    with tempfile.TemporaryDirectory(prefix="scrap-pagefind-") as tmp:
        out = Path(tmp) / "pagefind"
        asyncio.run(_build(records, out))
        files = {
            p.relative_to(out).as_posix(): p.read_bytes()
            for p in sorted(out.rglob("*"))
            if p.is_file()
        }
    css = files.get(UI_CSS, b"")
    unit = {k: v for k, v in files.items() if k.endswith(UNIT_TYPES)}
    unit["scrap-search.js"] = START
    return unit, css
