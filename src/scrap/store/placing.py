"""Where an added image's embed goes in a page's text (#480): at the end, or right
after the line a given passage ends on, inside the same list item or quote, so a
diagram sits under the question it belongs to and the page keeps its shape.

The text is parsed as the page is rendered (markdown.parser) to find the block that
line is in. A paragraph is split after it; a list item or a quote keeps the embed,
indented or quoted as a continuation; a block that cannot be split (a code block, a
table, display maths, a \\begin{...} environment, a heading) has the embed after it.
"""

import re

from markdown_it.token import Token

from ..markdown import parser
from .errors import InvalidError

# Blocks with no place for an embed inside: it goes after their last line
WHOLE = {"fence", "code_block", "math_block", "amsmath", "table_open", "html_block",
         "heading_open", "hr"}  # fmt: skip
CONTAINERS = ("list_item", "blockquote")
QUOTE = re.compile(r"^[ \t]*(?:>[ \t]?)+")
ITEM = re.compile(r"^((?:[ \t]*>[ \t]?)*)([ \t]*)([-*+]|\d{1,9}[.)])([ \t]+|$)")
DISPLAY = "$$"


def _display_maths(lines: list[str], code: set[int]) -> dict[int, int]:
    """Each $$ ... $$ block's lines (blank lines in it too, which the parser takes as
    paragraph breaks) as line -> its last line."""
    spans: dict[int, int] = {}
    i = 0
    while i < len(lines):
        s = lines[i].strip().lstrip(">").strip()
        one = len(s) > 2 * len(DISPLAY) - 1 and s.endswith(DISPLAY)
        if i in code or not s.startswith(DISPLAY) or one:
            i += 1
            continue
        j = next((j for j in range(i + 1, len(lines))
                  if lines[j].rstrip().endswith(DISPLAY)), len(lines) - 1)  # fmt: skip
        for line in range(i, j + 1):
            spans[line] = j
        i = j + 1
    return spans


def _find(tokens: list[Token], k: int) -> tuple[Token | None, list[Token]]:
    """The innermost leaf block holding line k, and the list items and quotes it is
    in, outermost first."""
    stack: list[Token] = []
    for t in tokens:
        kind = t.type.rsplit("_", 1)[0]
        if kind in CONTAINERS and t.nesting == 1:
            stack.append(t)
        elif kind in CONTAINERS and t.nesting == -1:
            stack.pop()
        elif t.map and t.map[0] <= k < t.map[1] and t.nesting != -1:
            if t.type in WHOLE or t.type == "paragraph_open":
                return t, stack
    return None, stack[:0]


def _prefix(lines: list[str], k: int, inside: list[Token]) -> tuple[str, str]:
    """What starts each line of the embed in the innermost list item or quote (its
    content indent, its > marks), and what a blank line there is."""
    if not inside:
        return "", ""
    c = inside[-1]
    if c.type == "blockquote_open":
        line = lines[k] if QUOTE.match(lines[k]) else lines[c.map[0]]  # type: ignore[index]
        mark = QUOTE.match(line)
        quote = mark[0] if mark else "> "
        quote = quote if quote.endswith((" ", "\t")) else quote + " "
        return quote, quote.rstrip()
    m = ITEM.match(lines[c.map[0]])  # type: ignore[index]
    if m is None:
        return "", ""
    gap = m[4] if 0 < len(m[4]) <= 4 and "\t" not in m[4] else " "
    col = len(m[1]) + len(m[2]) + len(m[3]) + len(gap)
    return m[1] + " " * (col - len(m[1])), m[1].rstrip()


def _unbalanced(text: str) -> bool:
    """Whether a paragraph's first lines leave inline code or maths open."""
    return text.count("`") % 2 == 1 or re.sub(r"\\.", "", text).count("$") % 2 == 1


def placed_after(body: str, after: str, new: list[str]) -> str:
    """body with the embeds new put right after the line on which the text after
    ends (it must occur exactly once, as edit_page's old: else InvalidError), as
    paragraphs of their own inside the same list item or quote; after a block that
    cannot be split (see the module docstring).

    >>> placed_after("Q1 Find x.\\nWorking:\\n\\nQ2", "Find x", ["![](e)"])
    'Q1 Find x.\\n\\n![](e)\\n\\nWorking:\\n\\nQ2'
    >>> placed_after("1. Show it.\\n   Answer: 4\\n2. Find y.", "Show", ["![](e)"])
    '1. Show it.\\n\\n   ![](e)\\n\\n   Answer: 4\\n2. Find y.'
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
    k = body.count("\n", 0, at + len(after) - 1)
    while k > 0 and not lines[k].strip():
        k -= 1  # the passage ended in blank lines: after the line before them
    tokens = parser().parse(body)
    leaf, inside = _find(tokens, k)
    code = {n for t in tokens if t.type in ("fence", "code_block") and t.map
            for n in range(*t.map)}  # fmt: skip
    maths = _display_maths(lines, code)
    prefix, blank = _prefix(lines, k, inside)
    ends = [k]  # where the embed may go, the first that keeps the page's shape
    if leaf is not None and leaf.map:
        end = leaf.map[1] - 1
        if leaf.type in WHOLE or _unbalanced("\n".join(lines[leaf.map[0] : k + 1])):
            ends = [end]  # cannot split it, or would cut `code` or $maths$ in two
        else:
            ends.append(end)
    if k in maths:
        ends = [max(e, maths[k]) for e in ends]
    shape, out = _shape(tokens), body
    for last in ends:
        out = _put(list(lines), last, prefix, blank, new, inside, leaf)
        if _shape(parser().parse(out)) == shape:
            return out
    return out  # the block's end: the parser's view of a split would differ


def _shape(tokens: list[Token]) -> list[tuple[str, int]]:
    """The text's blocks but its paragraphs (which a split or a blank line changes,
    and which the embeds are)."""
    leave = ("paragraph_open", "paragraph_close", "inline")
    return [(t.type, t.level) for t in tokens if t.type not in leave]


def _put(
    lines: list[str], last: int, prefix: str, blank: str, new: list[str],
    inside: list[Token], leaf: Token | None,
) -> str:  # fmt: skip
    """lines with the embeds after line last, each line starting with prefix."""
    if leaf is not None and leaf.map and leaf.type == "paragraph_open" and inside:
        for n in range(last + 1, leaf.map[1]):  # a lazy line after a split: kept in
            if not lines[n].startswith(prefix.rstrip()) or (
                inside[-1].type == "list_item_open"
                and len(lines[n]) - len(lines[n].lstrip()) < len(prefix)
            ):
                lines[n] = prefix + lines[n].lstrip()
    head, rest = lines[: last + 1], lines[last + 1 :]
    gap = blank
    while rest and not rest[0].strip():
        if not rest.pop(0):
            gap = ""  # a blank line ended the container there: so must this one
    embeds: list[str] = []
    for e in new:
        embeds += [blank, prefix + e] if embeds else [prefix + e]
    return "\n".join([*head, blank, *embeds, *([gap, *rest] if rest else [])])


def with_embeds(body: str, new: list[str], after: str | None = None) -> str:
    """body with the embeds new at its end, or after the line after ends on
    (placed_after)."""
    if new and after is not None:
        return placed_after(body, after, new)
    return "\n\n".join(x for x in (body.rstrip(), *new) if x)
