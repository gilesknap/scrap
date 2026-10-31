"""Where an added image's embed goes in a page's text (#480): at the end, or after
the Markdown block holding a given passage, so it never lands inside a code block,
a table, a list or a paragraph."""

import re

from .errors import InvalidError

FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
LIST = re.compile(r"^\s*([-*+]|\d{1,9}[.)])(\s|$)")
ATX = re.compile(r"^ {0,3}#{1,6}(\s|$)")
SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")


def _fences(lines: list[str]) -> dict[int, int]:
    """Each fenced code block's lines, as line -> the block's last line (its closing
    fence, else the last line of the text)."""
    spans: dict[int, int] = {}
    i = 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        mark = m[1]
        close = re.compile(rf"^\s*{re.escape(mark[0])}{{{len(mark)},}}\s*$")
        j = next((j for j in range(i + 1, len(lines)) if close.match(lines[j])),
                 len(lines) - 1)  # fmt: skip
        for line in range(i, j + 1):
            spans[line] = j
        i = j + 1
    return spans


def block_end(lines: list[str], k: int) -> int:
    """The last line of the Markdown block line k is in: a fenced code block to its
    closing fence; a heading alone (an ATX one, or a setext one to its underline); a
    list whole, past blank lines while an item or an indented line follows; else the
    run of lines up to a blank one (a paragraph, a table, a quote)."""
    fences = _fences(lines)
    if k in fences:
        return fences[k]
    if ATX.match(lines[k]):
        return k
    start = k
    while start > 0 and lines[start - 1].strip() and start - 1 not in fences:
        start -= 1
    listed = bool(LIST.match(lines[start]) or LIST.match(lines[k]))
    j = k
    while j + 1 < len(lines):
        line = lines[j + 1]
        if not line.strip():
            if not listed:
                break
            m = next((m for m in range(j + 1, len(lines)) if lines[m].strip()), None)
            if m is None or not (LIST.match(lines[m]) or lines[m][:1] in (" ", "\t")):
                break
            j = fences.get(m, m)
        elif j + 1 in fences:
            if not (listed and line[:1] in (" ", "\t")):
                break  # a fence after a paragraph starts a block of its own
            j = fences[j + 1]
        elif ATX.match(line):
            break
        elif SETEXT.match(line) and not listed:
            return j + 1  # the paragraph so far was a heading: it ends here
        else:
            j += 1
    return j


def placed_after(body: str, after: str, new: list[str]) -> str:
    """body with the embeds new put as paragraphs of their own after the Markdown
    block in which the text after ends (it must occur exactly once, as edit_page's
    old: else InvalidError), so a diagram goes under the question it belongs to and
    never inside a code block, table or list.

    >>> placed_after("Q1 Find x.\\n\\nWorking:\\n\\nQ2", "Find x", ["![](e)"])
    'Q1 Find x.\\n\\n![](e)\\n\\nWorking:\\n\\nQ2'
    >>> placed_after("| a |\\n|---|\\n| 1 |\\n| 2 |\\n\\nQ2", "| 1 |", ["![](e)"])
    '| a |\\n|---|\\n| 1 |\\n| 2 |\\n\\n![](e)\\n\\nQ2'
    """
    if not after.strip():
        raise InvalidError("after must not be empty")
    at, count, start = body.find(after), 0, 0
    while (found := body.find(after, start)) != -1 and count < 2:
        count, start = count + 1, found + 1  # overlapping ones count too
    if count != 1:
        why = "is not in the page's body" if count == 0 else "occurs more than once"
        raise InvalidError(f"after {why}: copy enough of the text to occur once")
    lines = body.split("\n")
    last = block_end(lines, body.count("\n", 0, at + len(after) - 1))
    head = "\n".join(lines[: last + 1]).rstrip()
    tail = "\n".join(lines[last + 1 :]).lstrip("\n")
    return "\n\n".join(x for x in (head, *new, tail) if x)


def with_embeds(body: str, new: list[str], after: str | None = None) -> str:
    """body with the embeds new at its end, or after the block after ends in
    (placed_after)."""
    if new and after is not None:
        return placed_after(body, after, new)
    return "\n\n".join(x for x in (body.rstrip(), *new) if x)
