"""has:open-questions (store.health): does a page's text have an "Open questions"
section that still has open content?

A section is a Markdown heading (any level, setext too; not in code, a quote or a
list) whose text is "Open questions", in any case and ignoring a trailing colon, up to
the next heading of the same or a higher level (deeper headings are inside it). It is
open when it has an unchecked task box (- [ ]); with task boxes that are all ticked it
is done; with none, it is open when it has any content at all (prose-style questions:
a paragraph, list, table or code), and an empty one is not.
"""

import re

from .markdown import parser, tasks

_HEADING = ("heading_open", "inline", "heading_close")


def _is_heading(text: str) -> bool:
    return text.strip().rstrip(":").rstrip().casefold() == "open questions"


def has_open_questions(text: str | None) -> bool:
    """True if text has an Open questions section with open content (module doc)."""
    if not text or "open questions" not in text.casefold():  # most: nothing to parse
        return False
    tokens = parser().parse(text)
    lines = re.split(r"\r\n?|\n", text)  # markdown-it's lines (its normalize)
    heads = [  # (token index, level) of each top-level heading
        (i, int(t.tag[1]))
        for i, t in enumerate(tokens)
        if t.type == "heading_open" and t.level == 0 and t.map
    ]
    for n, (i, level) in enumerate(heads):
        if not _is_heading(tokens[i + 1].content):
            continue
        peer = next((h[0] for h in heads[n + 1 :] if h[1] <= level), len(tokens))
        start = (tokens[i].map or (0, 0))[1]
        after = tokens[peer].map if peer < len(tokens) else None
        stop = after[0] if after else len(lines)
        done, total = tasks("\n".join(lines[start:stop]))
        if total:
            if done < total:
                return True
            continue
        body = [t for t in tokens[i + 3 : peer] if t.type != "hr"]
        # a deeper heading alone (its three tokens) is no content
        if any(t.type not in _HEADING for t in body):
            return True
    return False
