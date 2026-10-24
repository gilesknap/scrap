"""Reading one vault page: front matter, dates, ids, fields and tags."""

import hashlib
import math
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from ..store import CROCKFORD, DEFAULT_FIELDS, MAX_INT, MAX_PAGE, lines
from .model import (
    DROPPED,
    FIELDS,
    FOLDERS,
    KINDS,
    MAX_ALIASES,
    MAX_FIELDS,
    MAX_VALUE,
    STATUS,
    STATUSES,
    SUBTYPE,
    USED,
    Page,
    Plan,
)


class _Loader(yaml.SafeLoader):
    """safe_load with a cap on aliases."""

    aliases = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            self.aliases += 1
            if self.aliases > MAX_ALIASES:
                raise yaml.YAMLError("too many aliases")
        return super().compose_node(parent, index)


def _stamp(value: Any) -> str | None:
    """An ISO 8601 UTC time from a YAML date or datetime (or a string of one); a date
    alone is noon UTC."""
    if isinstance(value, str):
        text = value.strip()
        try:  # a date alone (2024-03-02 or 20240302) has no time part
            alone = "T" not in text.upper() and " " not in text
            value = date.fromisoformat(text) if alone else datetime.fromisoformat(text)
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC).isoformat(timespec="milliseconds")
        return value.replace("+00:00", "Z")
    if isinstance(value, date):
        return f"{value.isoformat()}T12:00:00.000Z"  # noon: the same day everywhere
    return None


def _ulid(key: str) -> str:
    """A ULID fixed by key (its time is 0): a page's path gives its capture the same
    id on every run, so a second run skips it."""
    n = int.from_bytes(hashlib.sha256(key.encode()).digest()[:10])
    return "".join(CROCKFORD[(n >> shift) & 31] for shift in range(125, -1, -5))


def _front(text: str) -> tuple[dict[str, Any] | None, str, str]:
    """The front matter (None if there is none), the body, and why the front matter
    could not be read ("" if it could, or there is none)."""
    if text.startswith("---\n"):
        head, sep, body = ("\n" + text[4:] + "\n").partition("\n---\n")
        if sep:
            try:
                fm = yaml.load(head, _Loader) or {}  # _Loader is a SafeLoader
            except (yaml.YAMLError, ValueError) as e:  # ValueError: a bad date
                return None, text, str(e).splitlines()[0][:80]
            if isinstance(fm, dict):
                return fm, body.removesuffix("\n"), ""
    return None, text, ""


def _skipped_dir(part: str) -> bool:
    return part in DROPPED or part.startswith((".", "_"))


def _read(plan: Plan, rel: str, path: Path) -> Page | None:
    try:
        stat = path.stat()
        if stat.st_size > MAX_PAGE:  # as for a page saved through the API (#62)
            plan.note("too large", rel, f"{stat.st_size:,} bytes, over {MAX_PAGE:,}")
            return None
        text = lines(path.read_text(encoding="utf-8", errors="replace"))
        mtime = datetime.fromtimestamp(stat.st_mtime, UTC)
    except OSError as e:
        plan.note("unreadable", rel, e.strerror or type(e).__name__)
        return None
    fm, body, why = _front(text)
    if why:
        plan.note("bad front matter", rel, why)
    if fm is None:
        plan.note("no front matter", rel)
        fm = {}
    folder = rel.split("/")[0] if "/" in rel else ""
    thoth = fm.get("type")
    if thoth is not None and (not isinstance(thoth, str) or thoth not in KINDS):
        plan.note("skipped", rel, f"type {thoth if isinstance(thoth, str) else '?'}")
        return None
    kind = KINDS.get(thoth or "", FOLDERS.get(folder, "note"))
    heading = re.match(r"\s*# (.+)\n?", body)
    title = fm.get("title")  # a scalar: a list could be an alias bomb
    title = " ".join(str(title).split()) if isinstance(title, str | int | float) else ""
    title = title or (heading[1].strip() if heading else Path(rel).stem)
    if heading and heading[1].strip() == title:  # the page shows its title already
        body = body[heading.end() :]
    fields: dict[str, Any] = dict(DEFAULT_FIELDS.get(kind, {}))
    for key, value in fm.items():
        if key in USED or value is None:
            continue
        name = FIELDS.get(key)
        if isinstance(value, date):
            value = value.isoformat()
        if name is None or not isinstance(value, str | bool | int | float):
            plan.note("unmapped field", rel, key)
            continue
        if isinstance(value, float) and not math.isfinite(value) or (
            isinstance(value, int) and not isinstance(value, bool)
            and abs(value) > MAX_INT
        ):  # fmt: skip
            plan.note("field dropped", rel, f"{key}: number out of range")
            continue
        if isinstance(value, str):
            value = " ".join(value.split())
            if len(value) > MAX_VALUE:  # the whole of it stays in the capture's text
                plan.note("field cut", rel, f"{key}: {len(value)} characters")
                value = value[: MAX_VALUE - 1] + "…"
        if name in ("status", "priority", "media_type"):
            value = str(value).lower()
            value = STATUS.get(value, value)
        if name == "status" and value not in STATUSES:
            plan.note("unknown status", rel, str(value))
        if name == "source" and "source" in fields:  # the first of url and source_url
            continue
        if name not in fields and len(fields) >= MAX_FIELDS:
            plan.note("field dropped", rel, f"{key}: over {MAX_FIELDS} fields")
            continue
        fields[name] = value
    if kind == "consume" and fields.get("media_type") in SUBTYPE:
        fields["subtype"] = SUBTYPE[fields["media_type"]]
    tags: list[str] = []
    raw_tags = fm.get("tags") or []
    for tag in raw_tags if isinstance(raw_tags, list) else [raw_tags]:
        if not isinstance(tag, str | int) or isinstance(tag, bool):
            plan.note("tag dropped", rel, type(tag).__name__)
            continue
        new = " ".join(str(tag).split()).lstrip("#").lower()[:64].strip()
        new = "/".join(part for part in new.split("/") if part.strip())
        if new != str(tag):
            plan.note("tag changed", rel, f"{tag!r} -> {new!r}")
        if new and new not in tags:
            tags.append(new)
    stamps = {}
    for key in ("created", "updated", "memory_date"):
        if fm.get(key) is not None:
            stamps[key] = _stamp(fm[key])
            if stamps[key] is None:
                plan.note("invalid date", rel, key)
    created = (
        stamps.get("created")
        or stamps.get("memory_date")
        or stamps.get("updated")
        or _stamp(mtime)
    )
    assert created
    updated = max(stamps.get("updated") or created, created)
    return Page(rel, text, title, kind, fields, tags, created, updated, body)
