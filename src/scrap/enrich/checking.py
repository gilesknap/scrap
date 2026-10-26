"""Enrich: the model's output within bounds, and the run's record."""

import json
import re
import sqlite3
import unicodedata
from collections.abc import Sequence
from typing import Any

from .. import actions, claude
from ..query import CONTROL, MEDIA
from ..store import MAX_TAG, WIKI_LINK, now, topics
from ..store.constants import MD_LINK
from .constants import (
    MAX_INVENTED,
    MAX_NEW_TAGS,
    MAX_NEW_TOPICS,
    MAX_RELATED,
    MAX_SUMMARY,
    MAX_TITLE,
    MAX_TOPIC_SOURCES,
    MAX_TOPIC_TITLE,
    MAX_WRITEUP,
    MIN_SOURCES,
)

# Control characters but tab and line feed (a write-up is Markdown, in lines)
TEXT_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# What else Markdown would make a link of, all but scrap's own [[...]]: a reference
# definition's line ([r]: url, not a footnote's [^1]:), a reference link [words][r] or
# [words][], an autolink <scheme:...> or <a@b>, and a scheme that linkify would link
# (https://, mailto:): its words stay, so nothing links outside the [[n]] mapping
REF_DEF = re.compile(r"^ {0,3}\[(?!\^)[^\]\n]+\]:.*$\n?", re.MULTILINE)
REF_LINK = re.compile(r"(?<!\[)!?\[([^\[\]\n]*)\]\[[^\[\]\n]*\]")
# Bounded (a scheme is at most 32 characters, an address's name 64), so a long run of
# scheme characters cannot make a search quadratic
AUTOLINK = re.compile(
    r"<((?:[a-z][a-z0-9+.-]{0,31}:|[^<>\s@]{1,64}@)[^<>\s]*)>", re.IGNORECASE
)
SCHEME = re.compile(r"\b(?:[a-z][a-z0-9+.-]{0,31}://|mailto:)", re.IGNORECASE)
# A cited page while the rest is stripped: \x00 never survives TEXT_CONTROL, so the
# model cannot write one
HELD = re.compile(r"\x00(\d+)\x00")
MAX_PASSES = 100  # each pass that changes the text takes something out of it


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
    media = out.get("media_type")
    intent, confidence = actions.clean_intent(out)
    items = actions.clean_items(out.get("items")) if intent == actions.INTENT else []
    return {
        "tags": tags[: MAX_NEW_TAGS * 2],
        "summary": summary if want_summary else "",
        "title": title,
        "media_type": media if link and media in MEDIA else "",
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


def unlinked(text: str) -> str:
    """Text with nothing Markdown or linkify would link: inline, reference and auto
    links and images, reference definitions, URL schemes and [[...]] keep only their
    words, and any "](" or "]:" left is split so it cannot start a link or a
    definition (in code spans too: safety first). Repeated until nothing changes, as
    taking one out can make another (https:a:////x). ValueError if it never settles."""
    for _ in range(MAX_PASSES):
        was = text
        text = REF_DEF.sub("", MD_LINK.sub(r"\1", text))
        text = SCHEME.sub("", AUTOLINK.sub(r"\1", REF_LINK.sub(r"\1", text)))
        text = WIKI_LINK.sub(lambda m: (m[2] or "").strip(), text)
        text = text.replace("](", "] (").replace("]:", "] :")
        if text == was:
            return text
    raise ValueError("the write-up's links did not settle")


def cited(text: str, slugs: Sequence[str]) -> str:
    """A write-up's links as the model wrote them, [[n]] or [[n|words]] with n a
    number of its index, as page links: [[slug]], [[slug|words]]; nothing else in it
    links (unlinked). The cited links are held aside (HELD) while the rest is
    stripped, so stripping can neither break one nor make one: a number not in the
    index, a name or a link made by taking something out keeps only its words."""
    held: list[str] = []

    def hold(m: re.Match[str]) -> str:
        target, words = m[1].strip(), unlinked((m[2] or "").strip())
        if target.isdecimal() and 1 <= int(target) <= len(slugs):
            slug = slugs[int(target) - 1]
            held.append(f"[[{slug}|{words}]]" if words else f"[[{slug}]]")
            return f"\x00{len(held) - 1}\x00"
        return words

    text = unlinked(WIKI_LINK.sub(hold, TEXT_CONTROL.sub("", text)))
    text = HELD.sub(lambda m: held[int(m[1])], text)
    # one next to its own ":" or "(" is not read as a definition or a destination
    return text.replace("]]:", "]] :").replace("]](", "]] (")


def checked_writeup(out: dict[str, Any], slugs: Sequence[str]) -> dict[str, str]:
    """A write-up within bounds: its summary one line, its text Markdown without
    control characters or any link but its cited pages' (cited: their words kept),
    at most MAX_WRITEUP characters. ValueError if it is not an answer, or its text is
    empty."""
    if not isinstance(out.get("summary"), str) or not isinstance(out.get("text"), str):
        raise ValueError("output lacks summary or text")
    summary = " ".join(CONTROL.sub(" ", out["summary"]).split())[:MAX_SUMMARY]
    text = out["text"][: 2 * MAX_WRITEUP].replace("\r\n", "\n").replace("\r", "\n")
    text = cited(text, slugs).strip()[:MAX_WRITEUP]
    if not text:
        raise ValueError("the write-up is empty")
    return {"summary": summary, "text": unicodedata.normalize("NFC", text)}


def numbers(raw: Any, most: int) -> list[int]:
    """The distinct numbers 1 to most in raw (a list), in order; [] if not a list."""
    out: list[int] = []
    for n in raw if isinstance(raw, list) else []:
        if type(n) is int and 1 <= n <= most and n not in out:
            out.append(n)
    return out


def checked_topics(
    out: dict[str, Any], n_pages: int, n_topics: int, taken: set[str]
) -> dict[str, Any]:
    """Topic discovery's output within bounds: new, at most MAX_NEW_TOPICS topics,
    each a title (one line), a key (topics.topic_key of the model's, else of the
    title) not taken (by a topic, in the trash too) nor given twice, and at least
    MIN_SOURCES distinct index numbers (at most MAX_TOPIC_SOURCES); add, each an
    existing topic's number with its new sources' numbers, once a topic. ValueError
    if it is not an answer at all."""
    if not isinstance(out.get("new"), list) or not isinstance(out.get("add"), list):
        raise ValueError("output lacks new or add")
    new: list[dict[str, Any]] = []
    keys = set(taken)
    for t in out["new"]:
        if not isinstance(t, dict) or len(new) >= MAX_NEW_TOPICS:
            continue
        title, raw = t.get("title"), t.get("key")
        title = title if isinstance(title, str) else ""
        title = " ".join(CONTROL.sub(" ", title).split())[:MAX_TOPIC_TITLE]
        raw = raw if isinstance(raw, str) else ""
        key = topics.topic_key(raw) or topics.topic_key(title)
        sources = numbers(t.get("sources"), n_pages)[:MAX_TOPIC_SOURCES]
        if title and key and key not in keys and len(sources) >= MIN_SOURCES:
            keys.add(key)
            new.append({"title": title, "key": key, "sources": sources})
    add: dict[int, list[int]] = {}
    for a in out["add"]:
        if not isinstance(a, dict):
            continue
        topic = a.get("topic")
        if type(topic) is not int or not 1 <= topic <= n_topics:
            continue
        got = add.setdefault(topic, [])
        got += [n for n in numbers(a.get("sources"), n_pages) if n not in got]
        del got[MAX_TOPIC_SOURCES:]
    return {
        "new": new,
        "add": [{"topic": t, "sources": s} for t, s in add.items() if s],
    }


def record(
    conn: sqlite3.Connection,
    run_id: int,
    done: claude.Completion | None,
    table: str = "enrich_run",
    **fields: Any,
) -> None:
    """Finish an enrich_run row (or a topic_run's: table): its outcome, and the
    response, usage and cost."""
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
    conn.execute(f"UPDATE {table} SET {names} WHERE id = ?", (*fields.values(), run_id))
