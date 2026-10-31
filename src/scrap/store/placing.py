"""Where an added image's embed goes in a page's text (#480): at the end, or right
after the line a given passage ends on, inside the same list item or quote, so a
diagram sits under the question it belongs to and the page keeps its shape.

The text is parsed as the page is rendered (markdown.parser) to find the block that
line is in. A paragraph is split after it; in a tight list (no blank lines between
items) the line ends with a hard break (a backslash) and the embed follows on the
next line, at the item's indent, so the list stays tight; in a loose list or a quote
the embed is a paragraph of its own there, indented or quoted as a continuation; a
block that cannot be split (a code block, a table, display maths, a \\begin{...}
environment, a heading) has the embed after it. Each place tried is parsed again and
kept only if the page's blocks, the list item or quote the embed is in, the lists'
tightness and the page's rendered text (the embed aside) are all as they were; if no
place passes, the embed goes at the end of the text, which is always safe.
"""

import re
from typing import NamedTuple

from markdown_it.token import Token

from ..markdown import parser
from .errors import InvalidError

# Blocks with no place for an embed inside: it goes after their last line
WHOLE = {"fence", "code_block", "math_block", "amsmath", "table_open", "html_block",
         "heading_open", "hr"}  # fmt: skip
CONTAINERS = ("list_item", "blockquote")
LISTS = ("bullet_list_open", "ordered_list_open")
# Possessive repeats: linear on a long line (a page may be one 1 MB line)
QUOTE = re.compile(r"^[ \t]*+(?:>[ \t]?+)++")
ITEM = re.compile(r"^((?:[ \t]*+>[ \t]?+)*+)([ \t]*+)([-*+]|\d{1,9}[.)])([ \t]++|$)")
EMBED_URL = re.compile(r"!\[[^\]\n]*+\]\(([^)\s]++)\)")
TAG = re.compile(r"<[^>]*+>")
DISPLAY = "$$"
TAB = 4  # CommonMark's tab stop


class Spot(NamedTuple):
    """Where line k is: its leaf block, the list items and quotes around it
    (outermost first), what starts an embed's line there and a blank line there,
    and whether its list is tight."""

    leaf: Token | None
    inside: list[Token]
    prefix: str
    blank: str
    tight: bool


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
    return None, []


def _tights(tokens: list[Token]) -> list[bool]:
    """Each list's tightness, in order (its paragraphs are hidden: no <p>)."""
    out, open_ = [], []
    for t in tokens:
        if t.type in LISTS:
            open_.append(len(out))
            out.append(True)
        elif t.type in ("bullet_list_close", "ordered_list_close"):
            open_.pop()
        elif t.type == "paragraph_open" and open_ and not t.hidden:
            out[open_[-1]] = False  # an item's paragraph shown: loose
    return out


def _spot(tokens: list[Token], lines: list[str], k: int) -> Spot:
    leaf, inside = _find(tokens, k)
    if not inside:
        return Spot(leaf, inside, "", "", False)
    c = inside[-1]
    if c.type == "blockquote_open":
        line = lines[k] if QUOTE.match(lines[k]) else lines[c.map[0]]  # type: ignore[index]
        mark = QUOTE.match(line.expandtabs(TAB))
        quote = mark[0] if mark else "> "
        quote = quote if quote.endswith(" ") else quote + " "
        return Spot(leaf, inside, quote, quote.rstrip(), False)
    m = ITEM.match(lines[c.map[0]].expandtabs(TAB))  # type: ignore[index]
    if m is None:
        return Spot(leaf, inside, "", "", False)
    gap = m[4] if 0 < len(m[4]) <= 4 else " "  # 5 or more: code, one counts
    col = len(m[1]) + len(m[2]) + len(m[3]) + len(gap)
    tight = leaf is None or leaf.type != "paragraph_open" or leaf.hidden
    if leaf is not None and leaf.type != "paragraph_open":  # by its item's paragraphs
        at = tokens.index(c)
        level = c.level + 1
        tight = all(t.hidden for t in tokens[at:]
                    if t.type == "paragraph_open" and t.level == level)  # fmt: skip
    return Spot(leaf, inside, m[1] + " " * (col - len(m[1])), m[1].rstrip(), tight)


def _unbalanced(text: str) -> bool:
    """Whether a paragraph's first lines leave inline code or maths open."""
    return text.count("`") % 2 == 1 or re.sub(r"\\.", "", text).count("$") % 2 == 1


def _indent(line: str) -> int:
    expanded = line.expandtabs(TAB)
    return len(expanded) - len(expanded.lstrip())


def _relazy(lines: list[str], last: int, spot: Spot) -> None:
    """Re-indent (or re-quote) the lazy lines of the paragraph after line last, so
    they stay in its list item or quote once the paragraph is split there."""
    leaf, inside, prefix = spot.leaf, spot.inside, spot.prefix
    if leaf is None or not leaf.map or leaf.type != "paragraph_open" or not inside:
        return
    quote = inside[-1].type == "blockquote_open"
    for n in range(last + 1, leaf.map[1]):  # the lazy lines that now start it
        line = lines[n]
        if quote and not line.expandtabs(TAB).startswith(prefix.rstrip()):
            lines[n] = prefix + QUOTE.sub("", line).lstrip()
        elif not quote and _indent(line) < len(prefix):
            lines[n] = prefix + line.lstrip()
        else:
            break  # a line of its own: those after it follow it, lazily or not


def _put(lines: list[str], last: int, spot: Spot, new: list[str]) -> str:
    """The embeds as paragraphs of their own after line last."""
    _relazy(lines, last, spot)
    head, rest = lines[: last + 1], lines[last + 1 :]
    blank, gap = spot.blank, spot.blank
    while rest and not rest[0].strip():
        if not rest.pop(0):
            gap = ""  # a blank line ended the container there: so must this one
    embeds: list[str] = []
    for e in new:
        embeds += [blank, spot.prefix + e] if embeds else [spot.prefix + e]
    return "\n".join([*head, blank, *embeds, *([gap, *rest] if rest else [])])


def _put_tight(lines: list[str], last: int, spot: Spot, new: list[str]) -> str:
    """The embeds after line last with no blank line, so a tight list stays tight:
    in a paragraph, line last ends with a hard break and each embed is a line of
    the paragraph, broken from the next."""
    _relazy(lines, last, spot)
    leaf = spot.leaf
    para = leaf is not None and leaf.map and leaf.type == "paragraph_open"
    more = bool(para and leaf and leaf.map and last < leaf.map[1] - 1)
    head, rest = lines[: last + 1], lines[last + 1 :]
    if para and not head[-1].rstrip(" ").endswith("\\"):
        head[-1] = head[-1].rstrip(" ") + "\\"
    embeds = [spot.prefix + e + "\\" for e in new]
    if not more:  # the paragraph ends with the last embed: no break after it
        embeds[-1] = embeds[-1][:-1]
    return "\n".join([*head, *embeds, *rest])


def _visible(html: str, new: list[str]) -> str:
    """Rendered text as a reader sees it, the embeds' images left out."""
    for url in (m[1] for e in new for m in EMBED_URL.finditer(e)):
        html = re.sub(rf'<img src="{re.escape(url)}"[^>]*+>', " ", html)
    return " ".join(TAG.sub(" ", html.replace("<br />", " ")).split())


def _holder(tokens: list[Token], new: list[str]) -> list[tuple[str, int]] | None:
    """The list items and quotes (type, first line) around the first embed's line."""
    stack: list[Token] = []
    for t in tokens:
        kind = t.type.rsplit("_", 1)[0]
        if kind in CONTAINERS and t.nesting == 1:
            stack.append(t)
        elif kind in CONTAINERS and t.nesting == -1:
            stack.pop()
        elif t.type == "inline" and new[0] in t.content:
            return [(c.type, c.map[0] if c.map else -1) for c in stack]
    return None


def _keeps(body_tokens: list[Token], html: str, out: str, spot: Spot,
           new: list[str]) -> bool:  # fmt: skip
    """Whether out has the page's blocks, lists' tightness and text, and the
    embed in the list item or quote line k is in."""
    md = parser()
    tokens = md.parse(out)
    leave = ("paragraph_open", "paragraph_close", "inline")
    same = [(t.type, t.level) for t in tokens if t.type not in leave] == [
        (t.type, t.level) for t in body_tokens if t.type not in leave
    ]
    held = [(c.type, c.map[0] if c.map else -1) for c in spot.inside]
    return (
        same
        and _tights(tokens) == _tights(body_tokens)
        and _holder(tokens, new) == held
        and _visible(md.render(out), new) == _visible(html, new)
    )


def at_end(body: str, new: list[str]) -> str:
    """body with the embeds new at its end."""
    return "\n\n".join(x for x in (body.rstrip(), *new) if x)


def placed_after(body: str, after: str, new: list[str]) -> str:
    """body with the embeds new put right after the line on which the text after
    ends (it must occur exactly once, as edit_page's old: else InvalidError), in
    the same list item or quote; see the module docstring.

    >>> placed_after("Q1 Find x.\\nWorking:\\n\\nQ2", "Find x", ["![](e)"])
    'Q1 Find x.\\n\\n![](e)\\n\\nWorking:\\n\\nQ2'
    >>> placed_after("1. Show it.\\n   Answer: 4\\n2. Find y.", "Show", ["![](e)"])
    '1. Show it.\\\\\\n   ![](e)\\\\\\n   Answer: 4\\n2. Find y.'
    """
    if not after.strip():
        raise InvalidError("after must not be empty")
    at, count, start = body.find(after), 0, 0
    while (found := body.find(after, start)) != -1 and count < 2:
        count, start = count + 1, found + 1  # overlapping ones count too
    if count != 1:
        why = "is not in the page's body" if count == 0 else "occurs more than once"
        raise InvalidError(f"after {why}: copy enough of the text to occur once")
    if not new:
        return body
    lines = body.split("\n")
    k = body.count("\n", 0, at + len(after) - 1)
    while k > 0 and not lines[k].strip():
        k -= 1  # the passage ended in blank lines: after the line before them
    md = parser()
    tokens = md.parse(body)
    spot = _spot(tokens, lines, k)
    code = {n for t in tokens if t.type in ("fence", "code_block") and t.map
            for n in range(*t.map)}  # fmt: skip
    maths = _display_maths(lines, code)
    ends = [k]  # where the embed may go, in order: the first that keeps the page
    leaf = spot.leaf
    if leaf is not None and leaf.map:
        end = leaf.map[1] - 1
        if leaf.type in WHOLE or _unbalanced("\n".join(lines[leaf.map[0] : k + 1])):
            ends = [end]  # cannot split it, or would cut `code` or $maths$ in two
        else:
            ends.append(end)
    if k in maths:
        ends = [max(e, maths[k]) for e in ends]
    put = _put_tight if spot.tight else _put
    html = md.render(body)
    for last in ends:
        out = put(list(lines), last, spot, new)
        if _keeps(tokens, html, out, spot, new):
            return out
    return at_end(body, new)  # no place inside keeps the page as it was


def with_embeds(body: str, new: list[str], after: str | None = None) -> str:
    """body with the embeds new at its end, or after the line after ends on
    (placed_after)."""
    if new and after is not None:
        return placed_after(body, after, new)
    return at_end(body, new)
