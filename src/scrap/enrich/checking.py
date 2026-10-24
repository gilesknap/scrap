"""Enrich: the model's output within bounds, and the run's record."""

import json
import sqlite3
import unicodedata
from typing import Any

from .. import actions, claude
from ..query import CONTROL
from ..store import MAX_TAG, now
from .constants import MAX_INVENTED, MAX_NEW_TAGS, MAX_RELATED, MAX_SUMMARY, MAX_TITLE


def clean_tag(tag: Any) -> str | None:
    if not isinstance(tag, str):
        return None
    new = " ".join(CONTROL.sub(" ", tag).split()).lstrip("#").lower().strip()
    new = unicodedata.normalize("NFC", new)
    return new if 0 < len(new) <= min(MAX_TAG, 40) else None


def checked(
    out: dict[str, Any], vocab: set[str], want_summary: bool, link: bool
) -> dict[str, Any]:
    """The model's output within bounds (ValueError if not an answer at all)."""
    if not all(k in out for k in ("tags", "summary", "title")):
        raise ValueError("output lacks a field")
    tags: list[str] = []
    invented = 0
    for raw in out["tags"] if isinstance(out["tags"], list) else []:
        tag = clean_tag(raw)
        if tag is None or tag in tags:
            continue
        if tag not in vocab:
            if invented >= MAX_INVENTED:
                continue
            invented += 1
        tags.append(tag)
    summary = out["summary"] if isinstance(out["summary"], str) else ""
    summary = " ".join(CONTROL.sub(" ", summary).split())[:MAX_SUMMARY]
    title = out["title"] if isinstance(out["title"], str) else ""
    title = " ".join(CONTROL.sub(" ", title).split())[:MAX_TITLE] if link else ""
    intent, confidence = actions.clean_intent(out)
    items = actions.clean_items(out.get("items")) if intent == actions.INTENT else []
    return {
        "tags": tags[: MAX_NEW_TAGS * 2],
        "summary": summary if want_summary else "",
        "title": title,
        "intent": intent,
        "confidence": confidence,
        "items": [{"text": t, "done": d} for t, d in items],
    }


def checked_related(out: dict[str, Any], n_candidates: int) -> list[int]:
    """Up to MAX_RELATED distinct, valid index numbers (ValueError if no answer)."""
    if not isinstance(out.get("related"), list):
        raise ValueError("output lacks related")
    related: list[int] = []
    for n in out["related"]:
        if type(n) is int and 1 <= n <= n_candidates and n not in related:
            related.append(n)
    return related[:MAX_RELATED]


def record(
    conn: sqlite3.Connection,
    run_id: int,
    done: claude.Completion | None,
    **fields: Any,
) -> None:
    """Finish an enrich_run row: its outcome, and the response, usage and cost."""
    if done is not None:
        fields.update(
            served_model=done.served_model,
            response=json.dumps(
                {"content": done.content, "stop_reason": done.stop_reason}
            ),
            usage=json.dumps(done.usage),
            cost_microusd=claude.cost_microusd(done.served_model, done.usage),
        )
    fields["finished_at"] = now()
    names = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE enrich_run SET {names} WHERE id = ?", (*fields.values(), run_id)
    )
