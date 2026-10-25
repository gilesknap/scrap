"""Enrich: the prompts and user turns of the topic calls (#261), discovery and a
topic's synthesis. All their data is quoted (prompts.quoted)."""

from collections.abc import Sequence
from typing import Any

from .. import claude
from ..markdown import plain
from ..store import unlink
from .constants import DISCOVERY_SCHEMA, TOPIC_NOTES, TOPIC_SCHEMA
from .prompts import Image, index_lines, one_line, quoted


def cut(text: str, most: int) -> str:
    """text, at most most characters (an ellipsis marks a cut)."""
    text = text.strip()
    if most <= 0:
        return ""
    return text if len(text) <= most else text[: most - 1] + "…"


def source_text(
    source: dict[str, Any], images: Sequence[Image], writeup: str, most: int
) -> str:
    """One source as the synthesis call sees it, at most most characters past its
    title line: its summary, then Claude's write-up of it, what was read from its
    images and its own text, each as much as is left."""
    left = most
    parts = []
    for label, text in (
        ("Summary", source["summary"] or ""),
        ("Claude's write-up of it", writeup),
        ("Read from its images", "\n".join(
            x for i in images for x in (i.get("description") or "", i.get("text") or "")
            if x.strip())),
        ("Its text", plain(source["body"])),
    ):  # fmt: skip
        if not text.strip() or left <= 0:
            continue
        piece = cut(text, left)
        left -= len(piece)
        parts.append(f"{label}:\n{piece}")
    return "\n".join(parts)


def topic_prompt() -> tuple[str, str]:
    """The synthesis call's fixed prompt and its version."""
    return claude.prompt("topic", TOPIC_SCHEMA)


def topic_message(
    page: Any,
    sources: Sequence[dict[str, Any]],
    texts: Sequence[str],
    guidance: str | None,
) -> list[dict[str, Any]]:
    """The synthesis call's user turn: the topic's title and the owner's notes (its
    text), the owner's guidance, and each source (numbered, as it is cited) with its
    title, kind and tags and its text (texts, made by source_text), all quoted."""
    notes = cut(plain(page["body"]), TOPIC_NOTES)
    lines = [
        f"Topic: {quoted(page['title'])}",
        "The owner's notes on it:",
        "<notes>",
        quoted(notes) or "(none)",
        "</notes>",
    ]
    if guidance:
        lines += ["The owner's guidance for this synthesis:", "<guidance>",
                  quoted(guidance), "</guidance>"]  # fmt: skip
    else:
        lines.append("The owner gave no guidance.")
    for n, (s, text) in enumerate(zip(sources, texts, strict=True), start=1):
        lines += [
            "",
            f"Source {n}: {quoted(one_line(unlink(s['title']), 200))}",
            f"Kind: {s['kind']}; tags: {quoted(', '.join(s['tags'])) or '(none)'}",
            "<source>",
            quoted(text) or "(empty)",
            "</source>",
        ]
    lines += ["", "Write the synthesis."]
    return [{"role": "user", "content": [{"type": "text", "text": "\n".join(lines)}]}]


def discovery_prompt() -> tuple[str, str]:
    """The discovery call's fixed prompt and its version."""
    return claude.prompt("topic-discovery", DISCOVERY_SCHEMA)


def discovery_message(
    pages: list[dict[str, Any]],
    topics: Sequence[dict[str, Any]],
    number: dict[str, int],
    rejected: Sequence[str],
) -> list[dict[str, Any]]:
    """The discovery call's user turn: the index of pages (numbered), the existing
    topics (numbered, each with its sources' index numbers: number maps a page id to
    its), and the keys of those the owner rejected (in the trash), all quoted."""
    listed = []
    for n, t in enumerate(topics, start=1):
        cited = " ".join(str(number[p]) for p in t["sources"] if p in number)
        title = quoted(one_line(t["title"], 120))
        listed.append(f"{n}. {title} ({quoted(t['key'])}): sources {cited or 'none'}")
    lines = [
        "The pages:",
        "<index>",
        index_lines(pages) or "(none)",
        "</index>",
        "Existing topics:",
        "<topics>",
        "\n".join(listed) or "(none)",
        "</topics>",
        "Rejected topics (never make these again): "
        + (quoted(", ".join(rejected)) or "(none)"),
        "",
        "Find the topics.",
    ]
    return [{"role": "user", "content": [{"type": "text", "text": "\n".join(lines)}]}]
