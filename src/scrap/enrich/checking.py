"""Enrich: the model's output within bounds, and the run's record."""

import json
import re
import sqlite3
import unicodedata
from collections.abc import Sequence
from typing import Any

from .. import actions, claude
from ..query import CONTROL
from ..store import MAX_TAG, WIKI_LINK, now
from ..store.constants import MD_LINK
from .constants import (
    MAX_INVENTED,
    MAX_NEW_TAGS,
    MAX_RELATED,
    MAX_SUMMARY,
    MAX_TITLE,
    MAX_WRITEUP,
)

# Control characters but tab and line feed (a write-up is Markdown, in lines)
TEXT_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# What else Markdown would make a link of, all but scrap's own [[...]]: a reference
# definition's line ([r]: url, not a footnote's [^1]:), a reference link [words][r] or
# [words][], an autolink <scheme:...> or <a@b>, and a scheme that linkify would link
# (https://, mailto:): its words stay, so nothing links outside the [[n]] mapping
REF_DEF = re.compile(r"^ {0,3}\[(?!\^)[^\]\n]+\]:.*$\n?", re.MULTILINE)
REF_LINK = re.compile(r"(?<!\[)!?\[([^\[\]\n]*)\]\[[^\[\]\n]*\]")
AUTOLINK = re.compile(r"<((?:[a-z][a-z0-9+.-]*:|[^<>\s@]+@)[^<>\s]*)>", re.IGNORECASE)
SCHEME = re.compile(r"\b(?:[a-z][a-z0-9+.-]*://|mailto:)", re.IGNORECASE)


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


def cited(text: str, slugs: Sequence[str]) -> str:
    """A write-up's links as the model wrote them, [[n]] or [[n|words]] with n a
    number of its index, as page links: [[slug]], [[slug|words]]. Any other [[...]]
    (a number not in the index, a name) is no link: its words stay, if it had any, so
    the model cannot link to a page that is not there."""

    def link(m: re.Match[str]) -> str:
        target, words = m[1].strip(), (m[2] or "").strip()
        if target.isdecimal() and 1 <= int(target) <= len(slugs):
            slug = slugs[int(target) - 1]
            return f"[[{slug}|{words}]]" if words else f"[[{slug}]]"
        return words

    return WIKI_LINK.sub(link, text)


def checked_writeup(out: dict[str, Any], slugs: Sequence[str]) -> dict[str, str]:
    """A write-up within bounds: its summary one line, its text Markdown without
    control characters or any link but its own (inline, reference and autolinks,
    reference definitions and URL schemes, which linkify would link: their words
    kept), its [[n]] links made page links (cited), at most MAX_WRITEUP characters.
    ValueError if it is not an answer, or its text is empty."""
    if not isinstance(out.get("summary"), str) or not isinstance(out.get("text"), str):
        raise ValueError("output lacks summary or text")
    summary = " ".join(CONTROL.sub(" ", out["summary"]).split())[:MAX_SUMMARY]
    text = out["text"].replace("\r\n", "\n").replace("\r", "\n")
    text = REF_DEF.sub("", MD_LINK.sub(r"\1", TEXT_CONTROL.sub("", text)))
    text = SCHEME.sub("", AUTOLINK.sub(r"\1", REF_LINK.sub(r"\1", text)))
    text = cited(text, slugs).strip()[:MAX_WRITEUP]
    if not text:
        raise ValueError("the write-up is empty")
    return {"summary": summary, "text": unicodedata.normalize("NFC", text)}


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
