"""An Excalidraw scene as a published drawing's SVG embeds it (#520; docs/reference/
public-site.md, "Drawings"): decoded, cleaned, and encoded again.

Excalidraw's exportToSvg with exportEmbedScene (0.18, data/encode.ts and
scene/export.ts) writes, inside the SVG's <metadata>::

    <!-- payload-type:application/vnd.excalidraw+json --><!-- payload-version:2 -->
    <!-- payload-start -->BASE64<!-- payload-end -->

BASE64 is the base64 of a JSON object {"version": "1", "encoding": "bstring",
"compressed": true, "encoded": E}, the JSON written with each byte of E as one
character (a "byte string"), and E the zlib deflate of the scene's JSON in UTF-8.
Excalidraw reads it back with loadFromBlob (decodeSvgBase64Payload), which takes the
first payload-start ... payload-end and the first payload-version.

Cleaning keeps only what a scene is, by an allow-list:

- the scene's own fields (type, version, source, elements, appState, files) and of
  appState only the background and grid; its source is "scrap" (Excalidraw writes the
  address of the app that exported it, which is scrap's own);
- elements that are not deleted, with only Excalidraw's own fields (no customData);
  every string in them goes through the page text's rule (links.scrub_text), less any
  embedded data: URL, and nested keys only if they are plain names; a link, by the
  page's link rules (link());
- every embedded image replaced by what images() makes of its bytes (the 2048-pixel
  preview of the page's photo it is), under a new id; one it maps to nothing is
  dropped, with the image elements that show it.
"""

import base64
import binascii
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Callable
from typing import Any

from .. import svg
from .errors import CheckError

__all__ = [
    "MAX_SCENE",
    "PAYLOAD_TYPE",
    "clean",
    "words",
    "decode",
    "encode",
    "metadata",
]

PAYLOAD_TYPE = "application/vnd.excalidraw+json"
TYPE = f"<!-- payload-type:{PAYLOAD_TYPE} -->"
VERSION = "<!-- payload-version:2 -->"
START, END = "<!-- payload-start -->", "<!-- payload-end -->"
BASE64 = re.compile(r"[A-Za-z0-9+/=]+")
# The scene's JSON, decompressed: more is refused, not inflated (a drawing's SVG is at
# most 20 MiB, and its scene holds the photo's preview once)
MAX_SCENE = 24 * 2**20
# An element's fields: Excalidraw 0.18's (element/types.ts), less customData. Nested
# objects (bindings, roundness, crop, boundElements) keep keys that are plain names
FIELDS = frozenset(
    """id type x y width height angle strokeColor backgroundColor fillStyle strokeWidth
    strokeStyle roughness opacity groupIds frameId index roundness seed version
    versionNonce isDeleted boundElements updated link locked text fontSize fontFamily
    textAlign verticalAlign containerId originalText autoResize lineHeight baseline
    points lastCommittedPoint startBinding endBinding startArrowhead endArrowhead
    elbowed fixedSegments startIsSpecial endIsSpecial pressures simulatePressure
    fileId status scale crop name polygon""".split()
)
KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,40}")
# A data: URL of some length in a string: never the page's own words; it goes
EMBEDDED = re.compile(r"data:[^,\s]{0,100};base64,[A-Za-z0-9+/=\s]{64,}", re.IGNORECASE)
DATA_URL = re.compile(r"data:image/(?:png|jpeg|webp|gif);base64,([A-Za-z0-9+/=]*)")
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]{1,30}")
GRID = {"gridSize": int, "gridStep": int, "gridModeEnabled": bool}


def _refuse(why: str) -> CheckError:
    return CheckError(f"Not published: a drawing {why}.", "bad_drawing")


def payload(root: ET.Element) -> str:
    """The base64 payload of an SVG Excalidraw exported with its scene (parsed with
    its comments, svg.parse(comments=True)): the root's one <metadata>, holding
    exactly the four marker comments, version 2, in order, and base64 after
    payload-start. CheckError otherwise: a scene anywhere else is not one."""
    metas = [el for el in root if el.tag == f"{{{svg.NS}}}metadata"]
    if len(metas) != 1:
        raise _refuse("has no single Excalidraw scene (one <metadata>)")
    kids = list(metas[0])
    said = [(k.text or "").strip() if k.tag is ET.Comment else None for k in kids]  # type: ignore[comparison-overlap]
    markers = [m[5:-4] for m in (TYPE, VERSION, START, END)]  # "<!-- " ... " -->"
    texts = [metas[0].text, *(k.tail for i, k in enumerate(kids) if i != 2)]
    if said != markers or any((t or "").strip() for t in texts):
        raise _refuse("has no single Excalidraw scene, as Excalidraw writes it")
    found = BASE64.fullmatch((kids[2].tail or "").strip())
    if found is None:
        raise _refuse("has a scene that is not base64")
    return found[0]


def decode(b64: str) -> dict[str, Any]:
    """The scene in an SVG's payload. CheckError if it is not one."""
    try:
        wrapper = json.loads(base64.b64decode(b64, validate=True).decode("latin-1"))
    except (binascii.Error, ValueError):
        raise _refuse("has a scene that cannot be read") from None
    if (
        not isinstance(wrapper, dict)
        or set(wrapper) != {"version", "encoding", "compressed", "encoded"}
        or wrapper["version"] != "1"
        or wrapper["encoding"] != "bstring"
        or wrapper["compressed"] is not True
        or not isinstance(wrapper["encoded"], str)
    ):
        raise _refuse("has a scene in a form Excalidraw does not write")
    try:
        inflate = zlib.decompressobj()
        raw = inflate.decompress(wrapper["encoded"].encode("latin-1"), MAX_SCENE + 1)
        if len(raw) > MAX_SCENE or inflate.unconsumed_tail:
            raise _refuse(f"scene is over {MAX_SCENE // 2**20} MiB")
        if not inflate.eof:
            raise ValueError("truncated")
        scene = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, zlib.error, RecursionError):
        raise _refuse("has a scene that cannot be read") from None
    if not isinstance(scene, dict) or scene.get("type") != "excalidraw":
        raise _refuse("has a payload that is not an Excalidraw scene")
    return scene


def encode(scene: dict[str, Any]) -> str:
    """A scene as the base64 payload Excalidraw writes (payload-version 2)."""
    text = json.dumps(scene, ensure_ascii=False, separators=(",", ":"))
    deflated = zlib.compress(text.encode("utf-8"), 9).decode("latin-1")
    wrapper = {"version": "1", "encoding": "bstring", "compressed": True,
               "encoded": deflated}  # fmt: skip
    data = json.dumps(wrapper, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(data.encode("latin-1")).decode("ascii")


def metadata(b64: str) -> str:
    """The markup Excalidraw puts first in the SVG for its scene, holding b64."""
    return (
        f"<!-- svg-source:excalidraw --><metadata>{TYPE}{VERSION}{START}{b64}{END}"
        "</metadata>"
    )


def words(text: str, scrub: Callable[[str], str]) -> str:
    """A text as published: no embedded data: URL, then scrubbed (links.scrub_text)."""
    return scrub(EMBEDDED.sub("", text))


def _strings(value: Any, scrub: Callable[[str], str], depth: int = 0) -> Any:
    """value with every string in it scrubbed, and only keys that are plain names."""
    if depth > 32:
        raise _refuse("has a scene nested too deeply")
    if isinstance(value, str):
        return words(value, scrub)
    if isinstance(value, list):
        return [_strings(v, scrub, depth + 1) for v in value]
    if isinstance(value, dict):
        return {
            k: _strings(v, scrub, depth + 1)
            for k, v in value.items()
            if isinstance(k, str) and KEY.fullmatch(k)
        }
    return value


def _files(
    files: Any, images: Callable[[bytes], bytes | None]
) -> tuple[dict[str, Any], dict[str, str]]:
    """The scene's images replaced by what images() makes of each, under a new id
    (the SHA-1 of its data URL, as Excalidraw names a file): the files kept, and
    each old id's new one."""
    if not isinstance(files, dict):
        return {}, {}
    out: dict[str, Any] = {}
    ids: dict[str, str] = {}
    for old, f in files.items():
        url = f.get("dataURL") if isinstance(f, dict) else None
        m = DATA_URL.fullmatch(url) if isinstance(url, str) else None
        if m is None:
            continue
        try:
            made = images(base64.b64decode(m[1], validate=True))
        except binascii.Error:
            continue
        if made is None:  # not a photo of the page: dropped
            continue
        data_url = "data:image/jpeg;base64," + base64.b64encode(made).decode("ascii")
        new = hashlib.sha1(data_url.encode()).hexdigest()  # noqa: S324  a name only
        created = f.get("created")
        out[new] = {
            "mimeType": "image/jpeg",
            "id": new,
            "dataURL": data_url,
            "created": created if isinstance(created, int) else 0,
        }
        ids[old] = new
    return out, ids


def clean(
    scene: dict[str, Any],
    images: Callable[[bytes], bytes | None],
    scrub: Callable[[str], str],
    link: Callable[[str], str | None],
) -> tuple[dict[str, Any], dict[str, str]]:
    """The scene as published (see the module docstring), and each kept image's old
    id's new one (so the SVG's own copy of it can follow)."""
    elements = scene.get("elements")
    if not isinstance(elements, list):
        raise _refuse("has a scene with no elements")
    files, ids = _files(scene.get("files"), images)
    kept: list[dict[str, Any]] = []
    for el in elements:
        if not isinstance(el, dict) or el.get("isDeleted") is True:
            continue
        el = {k: v for k, v in el.items() if k in FIELDS}
        if el.get("type") == "image":
            if not isinstance(el.get("fileId"), str) or el["fileId"] not in ids:
                continue
            el["fileId"] = ids[el["fileId"]]
        target = el.pop("link", None)
        el = _strings(el, scrub)  # (a new file id is hex: it stays as it is)
        el["link"] = link(target) if isinstance(target, str) and target else None
        kept.append(el)
    given = scene.get("appState")
    state: dict[str, Any] = given if isinstance(given, dict) else {}
    app: dict[str, Any] = {}
    bg = state.get("viewBackgroundColor")
    app["viewBackgroundColor"] = (
        bg if isinstance(bg, str) and COLOUR.fullmatch(bg) else "#ffffff"
    )
    for key, kind in GRID.items():
        v = state.get(key)
        if isinstance(v, kind) and (kind is bool or not isinstance(v, bool)):
            app[key] = v
    version = scene.get("version")
    out = {
        "type": "excalidraw",
        "version": version if isinstance(version, int) and version > 0 else 2,
        "source": "scrap",
        "elements": kept,
        "appState": app,
        "files": files,
    }
    return out, ids
