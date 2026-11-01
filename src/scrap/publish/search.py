"""The site's search index, the ``pagefind`` unit (docs/reference/public-site.md,
"What scrap builds"): built by the pagefind Python package (its pinned binary) from
the kept copies, each indexed as its text with every ``.katex`` element replaced by
the formula's TeX (its annotation), so search finds the TeX rather than KaTeX's glyph
spans. Pagefind's UI files go with it, and scrap-search.js, which starts the UI; its
stylesheet goes to the assets unit, as CSS lives only there.

The build is cached (under the kept copies' folder) by a digest of its records and
Pagefind's version, so an unchanged site is not indexed again, and it runs with a
timeout: a build that fails or takes too long raises SearchError, and the caller
leaves the site's last index in place (pending until a build works).

Each record goes in with add_custom_record. (add_directory would index them in one
call, but it makes a page's address /p/<slug>/, with a trailing slash, which no
data-pagefind-meta changes.)"""

import asyncio
import hashlib
import importlib.metadata
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import html5lib
from pagefind.index import PagefindIndex

from .katex import HTML, MATHML

__all__ = [
    "TIMEOUT",
    "UI_CSS",
    "SearchError",
    "build_index",
    "cached_css",
    "index_text",
]

TIMEOUT = 115.0  # seconds a build may take (with Pagefind's 5 s to close, about 120)
VERSION = importlib.metadata.version("pagefind")

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
# What a page's index text leaves out (the PWA's publish mode writes them): the
# site's own lines (.site), and the page's header, its title (the record's own),
# meta and dates lines and tag chips, so a result's excerpt is the page's text
SKIP = frozenset({"site", "meta", "dates", "tags"})


def _tex(el: ET.Element) -> str:
    for a in el.iter(f"{{{MATHML}}}annotation"):
        if a.get("encoding") == TEX:
            return "".join(a.itertext())
    return ""


def index_text(html: bytes | str) -> str:
    """A kept page's text for the index: its body's text, a KaTeX formula as its TeX,
    without the site's lines or the page's header.

    >>> index_text('<p>Area <span class="katex"><math><semantics><mi>r</mi>'
    ...   '<annotation encoding="application/x-tex">\\\\pi r^2</annotation>'
    ...   '</semantics></math><span class="katex-html">πr2</span></span></p>')
    'Area \\\\pi r^2'
    >>> index_text('<div class="site top">pages</div><h1>T</h1><p class="meta">Note</p>'
    ...   '<p class="tags"><a>#x</a></p><p>Body</p><div class="site foot">All</div>')
    'Body'
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
        if local == "h1" or SKIP & set((item.get("class") or "").split()):
            stack.append(f"{gap}{item.tail or ''}")
            continue
        if local == "span" and "katex" in (item.get("class") or "").split():
            stack.append(f"{gap}{item.tail or ''}")
            out.append(f" {_tex(item)} ")
            continue
        stack.append(f"{gap}{item.tail or ''}")
        stack.extend(reversed(list(item)))
        out.append(f"{gap}{item.text or ''}")
    return " ".join("".join(out).split())


class SearchError(Exception):
    """The index could not be built (Pagefind failed, or took over TIMEOUT)."""


async def _index(records: list[tuple[str, str, str]], out: Path) -> None:
    config = {"force_language": "en", "output_path": str(out)}
    async with PagefindIndex(config) as index:  # type: ignore[arg-type]
        for url, title, text in records:
            await index.add_custom_record(
                url=url, content=text, language="en", meta={"title": title}
            )


def _key(records: list[tuple[str, str, str]]) -> str:
    """The digest a build is cached by: its records, Pagefind's version and START."""
    raw = json.dumps([VERSION, START.decode(), records], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _command(records: Path, out: Path) -> list[str]:
    """The build, as a process of its own: this module run on a records file."""
    return [sys.executable, "-m", "scrap.publish.search", str(records), str(out)]


def _stop(proc: subprocess.Popen[bytes]) -> None:
    """End the build's process group, Pagefind's service with it (it would outlive a
    timed-out build otherwise), and reap it."""
    try:
        if os.name == "posix":
            os.killpg(
                proc.pid, signal.SIGKILL
            )  # what is left of the group, if anything
        elif proc.poll() is None:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()


def _run(records: list[tuple[str, str, str]], timeout: float) -> dict[str, bytes]:
    """Index records in a process of its own (and its own process group), killed
    with all it started if it takes over timeout."""
    with tempfile.TemporaryDirectory(prefix="scrap-pagefind-") as tmp:
        out = Path(tmp) / "pagefind"
        src = Path(tmp) / "records.json"
        src.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.Popen(  # noqa: S603  our own interpreter and module
            _command(src, out),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            _, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise SearchError(f"Pagefind took over {timeout:.0f} s") from None
        finally:
            _stop(proc)
            if proc.stderr is not None:
                proc.stderr.close()
        if proc.returncode:
            said = err.decode(errors="replace").strip().splitlines()[-1:] or [
                "no detail"
            ]
            raise SearchError(f"Pagefind failed: {said[0]}")
        return {
            p.relative_to(out).as_posix(): p.read_bytes()
            for p in sorted(out.rglob("*"))
            if p.is_file()
        }


def _load(cache: Path, key: str | None) -> tuple[dict[str, bytes], bytes] | None:
    """The cached build (of key; None: whichever it is), else None."""
    try:
        if key is not None and (cache / "key").read_text() != key:
            return None
        css = (cache / "css").read_bytes()
        unit = cache / "unit"
        files = {
            p.relative_to(unit).as_posix(): p.read_bytes()
            for p in sorted(unit.rglob("*"))
            if p.is_file()
        }
    except OSError:
        return None
    return (files, css) if files else None


def _save(cache: Path, key: str, unit: dict[str, bytes], css: bytes) -> None:
    """Swap the new build in for the cached one. Runs under the publish lock, so a
    .search-* folder beside it is a leftover of a crash: removed first."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    for left in cache.parent.glob(".search-*"):
        shutil.rmtree(left, ignore_errors=True)
    new = cache.parent / f".search-{uuid.uuid4().hex}"
    new.mkdir()
    for name, content in unit.items():
        (new / "unit" / name).parent.mkdir(parents=True, exist_ok=True)
        (new / "unit" / name).write_bytes(content)
    (new / "css").write_bytes(css)
    (new / "key").write_text(key)
    old = cache.parent / f".search-old-{uuid.uuid4().hex}"
    if cache.exists():
        os.replace(cache, old)
    os.replace(new, cache)
    shutil.rmtree(old, ignore_errors=True)


def cached_css(cache: Path) -> bytes | None:
    """Pagefind's UI stylesheet from the last build cached, for the assets unit
    while a build fails."""
    found = _load(cache, None)
    return found[1] if found else None


def build_index(
    records: list[tuple[str, str, str]], cache: Path | None = None,
    timeout: float | None = None,
) -> tuple[dict[str, bytes], bytes]:  # fmt: skip
    """The pagefind unit's files for records ((url, title, text), sorted) and Pagefind's
    UI stylesheet: from cache if it holds the build of these records, else built
    (and cached). SearchError if the build fails or takes over timeout (TIMEOUT).
    Runs the pagefind binary; call it from a thread with no event loop (a sync
    route's, or reconcile's)."""
    key = _key(records)
    if cache is not None and (hit := _load(cache, key)):
        return hit
    files = _run(records, TIMEOUT if timeout is None else timeout)
    css = files.get(UI_CSS, b"")
    unit = {k: v for k, v in files.items() if k.endswith(UNIT_TYPES)}
    unit["scrap-search.js"] = START
    if cache is not None:
        try:
            _save(cache, key, unit, css)
        except OSError:  # a cache only
            pass
    return unit, css


if (
    __name__ == "__main__"
):  # the build's own process (_run): records file, output folder
    _records = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    asyncio.run(_index([tuple(r) for r in _records], Path(sys.argv[2])))
