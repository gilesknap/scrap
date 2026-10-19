"""Checking drawings before they are stored or shown.

Model output is checked strictly: an element that breaks a rule is dropped with a
warning, and the rest are turned into Excalidraw element skeletons. (Human scenes from
the editor get a permissive check with the Excalidraw view.)
"""

import math
import re
from typing import Any, TypeGuard

from .claude import ELEMENT_TYPES, KINDS
from .store import CONTROL

__all__ = ["model_output"]

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
    if there is no text and no description (the run counts as invalid)."""
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
