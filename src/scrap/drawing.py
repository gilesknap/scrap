"""A photo's Excalidraw drawing: the current version, its history, a human edit and
Restore. Versions are rows of `derived` (kind excalidraw) and never change: saving or
restoring inserts a new current one. See docs/explanations/ingest.md.
"""

import json
import sqlite3
from typing import Any

from . import sanitise
from .ingest import put_derived
from .store import ConflictError, NotFoundError, Store, now, transaction

__all__ = ["StaleError", "current", "versions", "save", "restore", "excalidraw_file"]


class StaleError(ConflictError):
    """The drawing was changed since this edit began."""


KIND = "excalidraw"
VERSION = (
    "SELECT d.id, d.version, d.producer, d.run_id, d.author, d.data,"
    " d.superseded_at, d.created_at"
    " FROM derived d JOIN capture c ON c.id = d.capture_id"
    " JOIN page p ON p.id = c.page_id AND p.deleted_at IS NULL"
    " WHERE d.capture_id = ? AND d.source_sha256 = ? AND d.kind = 'excalidraw'"
)


def _photo(conn: sqlite3.Connection, cid: str, sha: str) -> None:
    """NotFoundError unless the capture (on a page not in the trash) has this photo."""
    if not conn.execute(
        "SELECT 1 FROM capture_blob cb JOIN capture c ON c.id = cb.capture_id"
        " JOIN page p ON p.id = c.page_id AND p.deleted_at IS NULL"
        " WHERE cb.capture_id = ? AND cb.sha256 = ?",
        (cid, sha),
    ).fetchone():
        raise NotFoundError(f"{cid}/{sha}")


def _meta(row: sqlite3.Row) -> dict[str, Any]:
    data = json.loads(row["data"] or "{}")
    return {
        "id": row["id"],
        "version": row["version"],
        "producer": row["producer"],
        "run_id": row["run_id"],
        "author": row["author"],
        "created_at": row["created_at"],
        "current": row["superseded_at"] is None,
        "superseded_at": row["superseded_at"],
        "format": data.get("format"),
        "restored_from": data.get("restored_from"),
    }


def _current(conn: sqlite3.Connection, cid: str, sha: str) -> sqlite3.Row | None:
    return conn.execute(VERSION + " AND d.superseded_at IS NULL", (cid, sha)).fetchone()


def _shown(conn: sqlite3.Connection, cid: str, sha: str) -> dict[str, Any]:
    row = _current(conn, cid, sha)
    if row is None:
        raise NotFoundError("no drawing")
    return {**_meta(row), "data": json.loads(row["data"])}


def current(store: Store, cid: str, sha: str) -> dict[str, Any]:
    """The current drawing: its version's details and its data (a model skeleton or a
    human scene, with the frame width and height). 404 if there is none."""
    with store.connect() as conn:
        _photo(conn, cid, sha)
        return _shown(conn, cid, sha)


def versions(store: Store, cid: str, sha: str) -> list[dict[str, Any]]:
    """Every version of the drawing, newest first, without their data."""
    with store.connect() as conn:
        _photo(conn, cid, sha)
        rows = conn.execute(VERSION + " ORDER BY d.version DESC", (cid, sha))
        return [_meta(row) for row in rows]


def _check_base(conn: sqlite3.Connection, cid: str, sha: str, base: int | None):
    row = _current(conn, cid, sha)
    version = row and row["version"]
    if version != base:  # someone saved, restored or reprocessed meanwhile
        raise StaleError(version)
    return row


def save(
    store: Store, cid: str, sha: str, base: int | None, data: Any, author: str
) -> dict[str, Any]:
    """Store a scene from the editor as the new current, human version. base is the
    version it was edited from (None: there was no drawing); ConflictError (409) if
    the current version is another, InvalidError (422) if the scene breaks a rule."""
    checked = sanitise.scene(data)
    with store.connect() as conn, transaction(conn):
        _photo(conn, cid, sha)
        old = _check_base(conn, cid, sha, base)
        if "width" not in checked and old is not None:  # keep the photo's frame
            frame = json.loads(old["data"])
            if "width" in frame and "height" in frame:
                checked.update(width=frame["width"], height=frame["height"])
        put_derived(
            conn, cid, sha, KIND, "human", now(), author=author,
            text=sanitise.scene_text(checked), data=checked,
        )  # fmt: skip
        return _shown(conn, cid, sha)  # the version written here, whatever comes next


def restore(
    store: Store, cid: str, sha: str, version: int, base: int, who: str
) -> dict[str, Any]:
    """Make an old version current again, as a copy (versions never change). base
    must be the current version (else 409), so a stale history view cannot restore
    over a newer edit; NotFoundError (404) if there is no such version."""
    with store.connect() as conn, transaction(conn):
        _photo(conn, cid, sha)
        _check_base(conn, cid, sha, base)
        old = conn.execute(
            "SELECT * FROM derived WHERE capture_id = ? AND source_sha256 = ?"
            " AND kind = 'excalidraw' AND version = ?",
            (cid, sha, version),
        ).fetchone()
        if old is None:
            raise NotFoundError(f"no version {version}")
        data = json.loads(old["data"]) | {"restored_from": version, "restored_by": who}
        put_derived(
            conn, cid, sha, KIND, old["producer"], now(), run_id=old["run_id"],
            author=old["author"], text=old["text"], data=data,
        )  # fmt: skip
        return _shown(conn, cid, sha)


# ---- a drawing as an .excalidraw file, for downloads and `scrap export`

BASE = {
    "angle": 0, "strokeColor": "#1e1e1e", "backgroundColor": "transparent",
    "fillStyle": "solid", "strokeWidth": 2, "strokeStyle": "solid", "roughness": 1,
    "opacity": 100, "groupIds": [], "frameId": None, "seed": 1, "version": 1,
    "versionNonce": 1, "isDeleted": False, "boundElements": None, "updated": 1,
    "link": None, "locked": False,
}  # fmt: skip
EXCALIFONT, LINE_HEIGHT = 5, 1.25


def _text(id_: str, x: float, y: float, text: str, size: float, **extra) -> dict:
    lines = text.splitlines() or [""]
    width = max(len(line) for line in lines) * size * 0.55  # Excalidraw re-measures
    return BASE | {
        "type": "text", "id": id_, "x": x, "y": y, "width": width,
        "height": len(lines) * size * LINE_HEIGHT, "text": text, "originalText": text,
        "fontSize": size, "fontFamily": EXCALIFONT, "textAlign": "left",
        "verticalAlign": "top", "containerId": None, "autoResize": True,
        "lineHeight": LINE_HEIGHT, "roundness": None,
    } | extra  # fmt: skip


def _skeleton_elements(skeleton: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Model skeletons as plain Excalidraw elements: an approximation of what the PWA
    draws (it converts them with Excalidraw itself), good enough to open and edit."""
    out: list[dict[str, Any]] = []
    shapes: dict[str, dict[str, Any]] = {}
    pairs = []  # (skeleton, element)
    taken = {s["id"] for s in skeleton if s.get("id")}

    def fresh(want: str) -> str:
        """An id no element has: the model's are kept, made ones step around them."""
        made, n = want, 1
        while made in taken:
            n += 1
            made = f"{want}-{n}"
        taken.add(made)
        return made

    for n, s in enumerate(skeleton):
        e = BASE | {
            "type": s["type"], "id": s.get("id") or fresh(f"e{n}"), "x": s["x"],
            "y": s["y"],
            "strokeColor": s.get("strokeColor", BASE["strokeColor"]),
        }  # fmt: skip
        if s["type"] == "text":
            e = _text(e["id"], s["x"], s["y"], s["text"], s.get("fontSize", 20)) | {
                "strokeColor": e["strokeColor"]
            }
        elif s["type"] in ("arrow", "line"):
            xs, ys = [p[0] for p in s["points"]], [p[1] for p in s["points"]]
            e |= {
                "points": s["points"], "width": max(xs) - min(xs),
                "height": max(ys) - min(ys), "lastCommittedPoint": None,
                "startBinding": None, "endBinding": None, "elbowed": False,
                "startArrowhead": s.get("startArrowhead"),
                "endArrowhead": "arrow" if s["type"] == "arrow" else None,
                "roundness": {"type": 2},
            }  # fmt: skip
        else:
            e |= {"width": s["width"], "height": s["height"], "roundness": None}
        out.append(e)
        shapes[e["id"]] = e
        pairs.append((s, e))
        label = s.get("label")
        if label:
            size = label.get("fontSize", 20)
            t = _text(fresh(f"{e['id']}-label"), e["x"], e["y"], label["text"], size)
            if s["type"] != "arrow":  # centred in its shape
                t["x"] = e["x"] + (e["width"] - t["width"]) / 2
                t["y"] = e["y"] + (e["height"] - t["height"]) / 2
            t |= {"containerId": e["id"], "textAlign": "center",
                  "verticalAlign": "middle"}  # fmt: skip
            e["boundElements"] = [{"type": "text", "id": t["id"]}]
            out.append(t)
    for s, e in pairs:
        for end, field in (("start", "startBinding"), ("end", "endBinding")):
            target = shapes.get((s.get(end) or {}).get("id", ""))
            if target is not None and target is not e:
                e[field] = {"elementId": target["id"], "focus": 0, "gap": 4}
                target["boundElements"] = (target["boundElements"] or []) + [
                    {"type": "arrow", "id": e["id"]}
                ]
    return out


def excalidraw_file(data: dict[str, Any]) -> bytes:
    """A stored drawing (skeleton or scene) as the bytes of an .excalidraw file."""
    if data.get("format") == "skeleton":
        elements = _skeleton_elements(data["elements"])
        background = "#ffffff"
    else:
        elements = data["elements"]
        background = (data.get("appState") or {}).get("viewBackgroundColor", "#ffffff")
    scene = {
        "type": "excalidraw",
        "version": 2,
        "source": "scrap",
        "elements": elements,
        "appState": {"viewBackgroundColor": background, "gridSize": None},
        "files": {},
    }
    return json.dumps(scene, indent=1).encode()
