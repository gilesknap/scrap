"""Checking drawings before they are stored or shown.

Model output is checked strictly: an element that breaks a rule is dropped with a
warning, and the rest are turned into Excalidraw element skeletons. Human scenes (from
the editor) are checked permissively, and one that breaks a rule is refused whole.
"""

import json
import math
import re
from typing import Any, TypeGuard

from .claude import ELEMENT_TYPES, KINDS
from .store import CONTROL, InvalidError

__all__ = ["model_output", "scene", "scene_text"]

ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
HEX = re.compile(r"#[0-9a-fA-F]{6}")
SHAPES = {"rectangle", "ellipse", "diamond"}
MAX_ELEMENTS, MAX_POINTS, MAX_TEXT = 1000, 200, 2000
FONT = (4, 200)
MAX_TAGS, MAX_TAG = 10, 64


def _finite(value: Any) -> TypeGuard[float]:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _clean(text: Any) -> str:
    return CONTROL.sub("", text if isinstance(text, str) else "").strip()


def _element(e: Any, width: int, height: int) -> dict[str, Any]:
    """One model element as a skeleton; raises ValueError naming the broken rule."""
    if not isinstance(e, dict) or e.get("type") not in ELEMENT_TYPES:
        raise ValueError("unknown type")
    kind = e["type"]
    x0, x1 = -width / 4, width * 5 / 4  # a quarter of the image beyond its edges
    y0, y1 = -height / 4, height * 5 / 4

    def inside(x: Any, y: Any) -> bool:
        return _finite(x) and _finite(y) and x0 <= x <= x1 and y0 <= y <= y1

    if not inside(e.get("x"), e.get("y")):
        raise ValueError("position outside the image")
    out: dict[str, Any] = {"type": kind, "x": e["x"], "y": e["y"]}
    if "id" in e:
        if not isinstance(e["id"], str) or not ID.fullmatch(e["id"]):
            raise ValueError("bad id")
        out["id"] = e["id"]
    if "strokeColor" in e:
        if not isinstance(e["strokeColor"], str) or not HEX.fullmatch(e["strokeColor"]):
            raise ValueError("bad colour")
        out["strokeColor"] = e["strokeColor"].lower()
    for key in ("fontSize", "labelFontSize"):
        if key in e and not (_finite(e[key]) and FONT[0] <= e[key] <= FONT[1]):
            raise ValueError(f"bad {key}")
    for key in ("text", "label"):
        if key in e and (not isinstance(e[key], str) or len(e[key]) > MAX_TEXT):
            raise ValueError(f"bad {key}")
    if kind in SHAPES:
        w, h = e.get("width"), e.get("height")
        if not (_finite(w) and _finite(h) and w >= 0 and h >= 0):
            raise ValueError("bad size")
        if not inside(e["x"] + w, e["y"] + h):
            raise ValueError("size outside the image")
        out.update(width=w, height=h)
    elif kind == "text":
        if not _clean(e.get("text")):
            raise ValueError("no text")
        out["text"] = _clean(e["text"])
        out["fontSize"] = e.get("fontSize", 20)
    else:  # arrow, line
        points = e.get("points")
        if not isinstance(points, list) or len(points) % 2 or not 4 <= len(points):
            raise ValueError("bad points")
        if not all(_finite(p) for p in points):
            raise ValueError("bad points")
        if len(points) > 2 * MAX_POINTS:
            raise ValueError("too many points")
        pairs = [points[i : i + 2] for i in range(0, len(points), 2)]
        if pairs[0] != [0, 0]:
            raise ValueError("points must start at 0, 0")
        if not all(inside(e["x"] + dx, e["y"] + dy) for dx, dy in pairs):
            raise ValueError("points outside the image")
        out["points"] = pairs
        if kind == "arrow":
            for end in ("start", "end"):
                if isinstance(e.get(end), str):
                    out[end] = {"id": e[end]}
            if e.get("startArrowhead") == "arrow":
                out["startArrowhead"] = "arrow"
    if (kind in SHAPES or kind == "arrow") and _clean(e.get("label")):
        out["label"] = {
            "text": _clean(e["label"]),
            "fontSize": e.get("labelFontSize", 20),
        }
    return out


def model_output(raw: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    """The model's structured output, checked: page fields cleaned, elements turned
    into Excalidraw skeletons (bad ones dropped), and the warnings. Raises ValueError
    if nothing usable is left (the run counts as invalid)."""
    warnings: list[str] = []
    kind = raw.get("kind")
    text, description = _clean(raw.get("text")), _clean(raw.get("description"))
    if not (text or description):
        raise ValueError("no text and no description")
    tags: list[str] = []
    given_tags = raw.get("tags")
    for tag in given_tags if isinstance(given_tags, list) else []:
        tag = " ".join(_clean(tag).lower().split()).replace(" ", "-")[:MAX_TAG]
        if tag and tag not in tags and len(tags) < MAX_TAGS:
            tags.append(tag)
    given = raw.get("elements")
    given = given if isinstance(given, list) else []
    if len(given) > MAX_ELEMENTS:
        warnings.append(f"{len(given) - MAX_ELEMENTS} elements over the limit dropped")
    elements, ids = [], set()
    for n, e in enumerate(given[:MAX_ELEMENTS]):
        try:
            element = _element(e, width, height)
            if "id" in element and element["id"] in ids:
                raise ValueError("duplicate id")
        except ValueError as error:
            warnings.append(f"element {n} dropped: {error}")
            continue
        if "id" in element:
            ids.add(element["id"])
        elements.append(element)
    if given and not elements:
        raise ValueError("every element was invalid")
    for n, element in enumerate(elements):
        for end in ("start", "end"):
            if end in element and element[end]["id"] not in ids:
                del element[end]
                warnings.append(f"element {n}: {end} names no element, unbound")
    return {
        "kind": kind if kind in KINDS else "other",
        "title": " ".join(_clean(raw.get("title")).split())[:200],
        "tags": tags,
        "description": description,
        "text": text,
        "elements": elements,
        "warnings": warnings,
    }


# Human scenes, as Excalidraw saves them
SCENE_TYPES = {*ELEMENT_TYPES, "freedraw"}
SCENE_BYTES = 5 * 2**20
MAX_FREEDRAW = 50_000
COLOUR = re.compile(
    r"transparent|[a-z]{3,20}|#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})"
    r"|rgba?\(\s*[0-9.]+%?\s*(?:,\s*[0-9.]+%?\s*){2,3}\)",
    re.IGNORECASE,
)
NUMBERS = ("x", "y", "width", "height", "angle", "fontSize", "strokeWidth", "opacity")
COLOURS = ("strokeColor", "backgroundColor")


def scene(data: Any) -> dict[str, Any]:
    """A human scene, checked and with embedded files stripped; InvalidError (a 422)
    if it breaks a rule."""
    if len(json.dumps(data)) > SCENE_BYTES:
        raise InvalidError("scene over 5 MB")
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise InvalidError("a scene is an object with an elements list")
    elements = []
    for n, e in enumerate(data["elements"]):
        if not isinstance(e, dict) or e.get("type") not in SCENE_TYPES:
            raise InvalidError(f"element {n}: type not allowed")
        for key in NUMBERS:
            if key in e and not _finite(e[key]):
                raise InvalidError(f"element {n}: {key} must be a finite number")
        for key in COLOURS:
            if key in e and not (
                isinstance(e[key], str) and COLOUR.fullmatch(e[key].strip())
            ):
                raise InvalidError(f"element {n}: bad {key}")
        points = e.get("points", [])
        limit = MAX_FREEDRAW if e["type"] == "freedraw" else MAX_POINTS
        if not isinstance(points, list) or len(points) > limit:
            raise InvalidError(f"element {n}: too many points")
        for point in points:
            if not (
                isinstance(point, list)
                and len(point) == 2
                and all(_finite(c) for c in point)
            ):
                raise InvalidError(f"element {n}: bad point")
        link = e.get("link")
        if link is not None and not (
            isinstance(link, str) and re.match(r"https?://", link, re.IGNORECASE)
        ):
            raise InvalidError(f"element {n}: links must be http(s)")
        for key in ("text", "originalText"):
            if key in e and not isinstance(e[key], str):
                raise InvalidError(f"element {n}: {key} must be a string")
        elements.append(e)
    out: dict[str, Any] = {"elements": elements}  # files (embedded images) dropped
    background = (data.get("appState") or {}).get("viewBackgroundColor")
    if isinstance(background, str) and COLOUR.fullmatch(background):
        out["appState"] = {"viewBackgroundColor": background}
    return out


def scene_text(checked: dict[str, Any]) -> str:
    """The writing in a scene, one text element a line: what search indexes."""
    return "\n".join(
        _clean(e.get("text"))
        for e in checked["elements"]
        if e["type"] == "text" and not e.get("isDeleted") and _clean(e.get("text"))
    )
