"""Reading one page's file: its front matter, title, kind, dates, fields and tags.

The front matter is read with a YAML safe loader (no tags that build objects, a cap
on aliases). What scrap's export writes is read back as it was: `id`, `kind`,
`tags`, `created`, `updated`, a todo's `due` and `priority`, `made_by`, `attachments`,
every other key as a field and `fields` for one whose name is one of those. A file
from another tool (Obsidian) is read the same way, so its own keys become fields."""

import hashlib
import math
import re
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Any

import yaml

from ..store import (
    CROCKFORD,
    DEFAULT_FIELDS,
    KINDS,
    MAX_INT,
    InvalidError,
    clean_tags,
    lines,
)
from ..store.constants import ULID
from .model import (
    CREATED,
    DATES,
    MAX_ALIASES,
    MAX_FIELDS,
    MAX_VALUE,
    OWN,
    UPDATED,
    Page,
    Plan,
)

MAX_KEY = 40  # a field's name, as the API takes it
HEADING = re.compile(r"\s*#[ \t]+(.+)")  # a first line `# Title`


class _Loader(yaml.SafeLoader):
    """safe_load with a cap on aliases."""

    aliases = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            self.aliases += 1
            if self.aliases > MAX_ALIASES:
                raise yaml.YAMLError("too many aliases")
        return super().compose_node(parent, index)


def stamp(value: Any) -> str | None:
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
        try:
            value = value.astimezone(UTC).isoformat(timespec="milliseconds")
        except OverflowError:  # year 1 east of UTC: before the first datetime
            return None
        return value.replace("+00:00", "Z")
    if isinstance(value, date):
        return f"{value.isoformat()}T12:00:00.000Z"  # noon: the same day everywhere
    return None


def ulid(key: str) -> str:
    """A ULID fixed by key (its time is 0): a file's path and bytes give its capture
    the same id on every run, so a second run skips it."""
    n = int.from_bytes(hashlib.sha256(key.encode()).digest()[:10], "big")
    return "".join(CROCKFORD[(n >> shift) & 31] for shift in range(125, -1, -5))


def front(text: str) -> tuple[dict[str, Any] | None, str, str]:
    """The front matter (None if there is none), the body, and why the front matter
    could not be read ("" if it could, or there is none). The body is as written,
    less the blank line after the front matter and the file's last line end (scrap's
    export adds both)."""
    if text.startswith("---\n"):
        head, sep, body = ("\n" + text[4:] + "\n").partition("\n---\n")
        if sep:
            try:
                fm = yaml.load(head, _Loader) or {}  # _Loader is a SafeLoader
            except (yaml.YAMLError, ValueError, OverflowError) as e:  # a bad date
                return None, text.removesuffix("\n"), str(e).splitlines()[0][:80]
            if isinstance(fm, dict):
                body = body.removesuffix("\n").removeprefix("\n").removesuffix("\n")
                return fm, body, ""
            return None, text.removesuffix("\n"), "not a map of keys"
    return None, text.removesuffix("\n"), ""


def _value(plan: Plan, rel: str, key: str, value: Any) -> Any:
    """A field's value as scrap stores it (flat), or None if it cannot be (noted)."""
    if isinstance(value, datetime | date):
        value = stamp(value) if isinstance(value, datetime) else value.isoformat()
    if not isinstance(value, str | bool | int | float):
        plan.note("field not imported", rel, f"{key}: not a single value")
        return None
    if isinstance(value, float) and not math.isfinite(value) or (
        isinstance(value, int) and not isinstance(value, bool) and abs(value) > MAX_INT
    ):  # fmt: skip
        plan.note("field not imported", rel, f"{key}: number out of range")
        return None
    if isinstance(value, str):
        if len(value) > MAX_VALUE:  # the whole of it stays in the capture's text
            plan.note("field cut", rel, f"{key}: {len(value)} characters")
            value = value[: MAX_VALUE - 1] + "…"
    return value


def _fields(plan: Plan, rel: str, kind: str, fm: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = dict(DEFAULT_FIELDS.get(kind, {}))
    given = {k: v for k, v in fm.items() if k not in OWN and k not in DATES}
    nested = fm.get("fields")
    if isinstance(nested, dict):  # a field named as one of OWN
        given |= nested
    elif nested is not None:
        plan.note("field not imported", rel, "fields: not a map")
    if kind == "todo":  # its own columns (store.todo_columns takes them out)
        given |= {k: fm[k] for k in ("due", "priority") if fm.get(k) is not None}
    for key, value in given.items():
        if value is None:
            continue
        name = str(key)  # as written: a scrap export's are free text, quoted
        if not name.strip() or len(name) > MAX_KEY:
            plan.note("field not imported", rel, f"{name[:40]!r}: not a field name")
            continue
        value = _value(plan, rel, name, value)
        if value is None:
            continue
        if name not in fields and len(fields) >= MAX_FIELDS:
            plan.note("field not imported", rel, f"{name}: over {MAX_FIELDS} fields")
            continue
        fields[name] = value
    return fields


def _tags(plan: Plan, rel: str, raw: Any, most: int) -> list[str]:
    """The front matter's tags (a list, or a string of them split at commas and
    spaces, as Obsidian has them), each as scrap keeps tags."""
    if isinstance(raw, str):
        raw = [t for t in re.split(r"[,\s]+", raw) if t]
    elif raw is None:
        raw = []
    elif not isinstance(raw, list):
        raw = [raw]
    tags: list[str] = []
    for tag in raw:
        if not isinstance(tag, str | int) or isinstance(tag, bool):
            plan.note("tag not imported", rel, type(tag).__name__)
            continue
        try:
            new = clean_tags([str(tag)])[0]  # as an edit keeps it
        except InvalidError:
            plan.note("tag not imported", rel, repr(str(tag)[:80]))
            continue
        if new not in tags:
            if len(tags) >= most:
                plan.note("tag not imported", rel, f"{new}: over {most} tags")
                continue
            tags.append(new)
    return tags


def read(plan: Plan, rel: str, data: bytes, mtime: datetime, most_tags: int) -> Page:
    """A page from its file's bytes (at most MAX_PAGE), problems noted on plan."""
    text = lines(data.decode("utf-8", errors="replace").removeprefix("\ufeff"))
    fm, body, why = front(text)
    if why:
        plan.note("front matter not read", rel, why)
    fm = fm or {}
    kind = fm.get("kind")
    if kind is not None and kind not in KINDS:
        plan.note("kind not known", rel, f"{str(kind)[:40]}: a note")
    kind = kind if kind in KINDS else "note"
    title = fm.get("title")  # a scalar: a list could be an alias bomb
    title = str(title).strip() if isinstance(title, str | int | float) else ""
    if "\n" in title:  # one line, as a title is
        title = " ".join(title.split())
    heading = HEADING.match(body)
    stem = PurePosixPath(rel).stem
    title = (title or (heading[1].strip() if heading else "") or stem)[:200]
    page_id = fm.get("id")
    page_id = page_id.upper() if isinstance(page_id, str) else None
    if page_id is not None and not ULID.fullmatch(page_id):
        plan.note("id not used", rel, "not a ULID")
        page_id = None
    stamps = {}
    for key in (*CREATED, *UPDATED):
        if fm.get(key) is not None:
            stamps[key] = stamp(fm[key])
            if stamps[key] is None:
                plan.note("date not read", rel, key)
    created = next((stamps[k] for k in CREATED if stamps.get(k)), None)
    updated = next((stamps[k] for k in UPDATED if stamps.get(k)), None)
    created = created or updated or stamp(mtime)
    assert created
    attachments = fm.get("attachments") or []
    if not isinstance(attachments, list):
        attachments = [attachments]
    made_by = fm.get("made_by")
    page = Page(
        path=rel,
        text=text,
        title=title,
        kind=kind,
        fields=_fields(plan, rel, kind, fm),
        tags=_tags(plan, rel, fm.get("tags"), most_tags),
        created_at=created,
        updated_at=max(updated or created, created),
        body=body,
        id=page_id,
        made_by=made_by if isinstance(made_by, str) else "human",
        attachments=[a for a in attachments if isinstance(a, str)],
    )
    return page
