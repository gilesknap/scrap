"""A page's Mermaid diagrams as its unit holds them (#525;
docs/reference/public-site.md, "Diagrams"). The PWA draws each diagram on the page
twice, in the light and the dark theme, with SVG labels (no foreignObject), and
uploads both SVGs beside the page's HTML, which shows them as
``scrap-diagram:<n>-light`` and ``-dark`` images. scrap never trusts them: each goes
through scrap's sanitiser (svg.sanitise: no script, no foreignObject, no link out,
CSS that fetches nothing), then its text and attribute values are scrubbed as a code
block's are (links.scrub_code: scrap's own addresses hidden, #529), and a <style>
holding one of them is refused. Each published SVG is an img-*.svg, counted in the
caps as any image (files.page_files)."""

import xml.etree.ElementTree as ET
from collections.abc import Callable

from .. import svg
from ..store import InvalidError, TooLargeError
from .checker import DIAGRAM_PREFIX, Checked
from .errors import CheckError
from .files import MAX_FILES
from .links import PRIVATE_LINK, private_text, scrub_code

__all__ = ["MAX_DIAGRAM", "THEMES", "clean_diagram", "page_diagrams"]

MAX_DIAGRAM = 2 * 2**20  # an uploaded diagram's SVG, in one theme
THEMES = ("light", "dark")


def _refuse(why: str) -> CheckError:
    return CheckError(f"Not published: a diagram {why}.", "bad_diagram")


def _too_big() -> CheckError:
    return CheckError(
        f"Not published: a diagram is over {MAX_DIAGRAM // 2**20} MiB.",
        "file_too_large",
    )


def _scrubbed(root: ET.Element, scrub: Callable[[str], str]) -> None:
    """Each text and attribute value scrubbed; a <style> that would change refused
    (CSS is not rewritten)."""
    stack = [root]
    while stack:
        el = stack.pop()
        for key, value in el.attrib.items():
            el.set(key, scrub(value))
        if el.tag.rpartition("}")[2] == "style":
            if scrub(el.text or "") != (el.text or ""):
                raise _refuse("has an address of scrap's in its style")
        elif el.text:
            el.text = scrub(el.text)
        for child in el:
            child.tail = scrub(child.tail) if child.tail else child.tail
            stack.append(child)
    # A label Mermaid wrapped is one <text> of several pieces, a long word split
    # between them: read whole, one that still names scrap is said as a private link
    for el in root.iter():
        if el.tag.rpartition("}")[2] in svg.WORDS and private_text(
            "".join(el.itertext())
        ):
            el.text = PRIVATE_LINK
            el[:] = []


def clean_diagram(text: str, scrub: Callable[[str], str] = scrub_code) -> bytes:
    """A diagram's SVG as published (see the module docstring); CheckError
    (bad_diagram, or file_too_large) if it cannot be."""
    data = text.encode("utf-8")
    if len(data) > MAX_DIAGRAM:
        raise _too_big()
    if "<![CDATA[" in text:  # Mermaid writes none; text in it would go out as is
        raise _refuse("has a CDATA section")
    try:
        safe = svg.sanitise(data, MAX_DIAGRAM)
        root = svg.parse(safe, svg.GROWTH * MAX_DIAGRAM)
    except (InvalidError, TooLargeError) as e:
        raise _refuse(f"cannot be made safe ({e})") from None
    except RecursionError:
        raise _refuse("is nested too deeply") from None
    _scrubbed(root, scrub)
    made = svg.serialise(root).encode("utf-8")
    if len(made) > MAX_DIAGRAM:
        raise _too_big()
    return made


def page_diagrams(
    checked: Checked, uploads: dict[str, tuple[str, str]]
) -> dict[str, bytes]:
    """Each diagram image the checked page shows, by <n>-<theme>, as published.
    uploads: each diagram's (light, dark) SVGs, by its key n. The page must show
    both of a diagram's images, each diagram it shows must be uploaded, and nothing
    else uploaded."""
    shown = list(dict.fromkeys(
        sha.removeprefix(DIAGRAM_PREFIX) for sha, _ in checked.blobs
        if sha.startswith(DIAGRAM_PREFIX)
    ))  # fmt: skip
    keys = list(dict.fromkeys(name.rpartition("-")[0] for name in shown))
    for key in keys:
        if any(f"{key}-{theme}" not in shown for theme in THEMES):
            raise _refuse("on the page is not shown in both themes")
        if key not in uploads:
            raise _refuse("on the page was not sent with it")
    if set(uploads) - set(keys):
        raise _refuse("was sent that the page does not show")
    if len(keys) * len(THEMES) > MAX_FILES:  # before any is cleaned (files counts all)
        raise CheckError(
            f"Not published: a page publishes at most {MAX_FILES} images, drawings,"
            " diagrams (two images each) and files.",
            "too_many_files",
        )
    out: dict[str, bytes] = {}
    for key in keys:
        for theme, text in zip(THEMES, uploads[key], strict=True):
            out[f"{key}-{theme}"] = clean_diagram(text)
    return out
