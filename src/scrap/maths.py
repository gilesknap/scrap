"""Maths in page text, parsed as the PWA parses it (web/src/mathrules.ts, the same rules
line for line): $...$ inline, $$...$$ inline or on lines of its own, and a top-level
amsmath environment (\\begin{align} ... \\end{align}). Their tokens are mdit-py-plugins'
(dollarmath's math_inline, math_inline_double and math_block; amsmath's amsmath), so a
formula's _, * and [[ are neither emphasis nor a link to search or link rewriting.

The plugins' own rules are swapped for these: dollarmath's inline rule reads the text's
last character as the one before a $ at its start (so "$x$ is 5" was not maths) and
looks past posMax, and its block rule, like amsmath's, reads on from every opening
line that is not closed (a page of them took quadratic time). Here a line that opens
another block of the same kind ends the search, and so does a line out of a list item.

Money is not maths: an opening $ is not followed by a space nor preceded by a digit, a
closing $ not preceded by a space nor followed by a digit, so "$5 and $10" is text."""

import re

from markdown_it import MarkdownIt
from markdown_it.common.utils import isWhiteSpace
from markdown_it.rules_block import StateBlock
from markdown_it.rules_inline import StateInline
from mdit_py_plugins.amsmath import RE_OPEN, amsmath_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin

__all__ = ["maths_plugin"]

AMS_OPEN = re.compile(RE_OPEN)
# The block rules amsmath may interrupt (as amsmath_plugin registers it)
AMS_ALT = ["paragraph", "reference", "blockquote", "list", "footnote_def"]


def _escaped(src: str, pos: int) -> bool:
    """Whether the character at pos is escaped: an odd run of backslashes before it."""
    n = 0
    while pos - n - 1 >= 0 and src[pos - n - 1] == "\\":
        n += 1
    return n % 2 == 1


def _inline(state: StateInline, silent: bool) -> bool:
    """$tex$ and $$tex$$ in a line's text (mathrules.ts inline)."""
    src, pos, end_max = state.src, state.pos, state.posMax

    def digit(i: int) -> bool:
        return 0 <= i < len(src) and src[i] in "0123456789"

    def space(i: int) -> bool:
        return isWhiteSpace(ord(src[i]))

    if src[pos] != "$" or pos + 1 >= end_max or digit(pos - 1) or _escaped(src, pos):
        return False
    double = src[pos + 1] == "$"
    if not double and space(pos + 1):
        return False
    width = 2 if double else 1
    start = pos + width
    while True:  # to the closing $ (or $$)
        end = src.find("$", start)
        if end < 0 or end + width > end_max:
            return False
        if _escaped(src, end) or (double and src[end + 1 : end + 2] != "$"):
            start = end + 1
        else:
            break
    tex = src[pos + width : end]
    if not tex or (not double and space(end - 1)) or digit(end + width):
        return False
    if not silent:
        token = state.push("math_inline_double" if double else "math_inline", "math", 0)
        token.content = tex
        token.markup = "$$" if double else "$"
    state.pos = end + width
    return True


def _line(state: StateBlock, i: int) -> str:
    """Line i's text, from its first character (after its indent, any quote marker)."""
    return state.src[state.bMarks[i] + state.tShift[i] : state.eMarks[i]]


def _block(state: StateBlock, start: int, end: int, silent: bool) -> bool:
    """$$ at a line's start, to a line that ends $$ (that one, if it is more than $$),
    with no blank line between (mathrules.ts block)."""
    if state.sCount[start] - state.blkIndent >= 4:
        return False  # indented code
    first = _line(state, start).strip()
    if not first.startswith("$$"):
        return False
    nxt = start
    if len(first) <= 3 or not first.endswith("$$"):
        while True:
            nxt += 1
            if nxt >= end:
                return False
            line = _line(state, nxt).strip()
            if not line or state.sCount[nxt] < state.blkIndent:
                return False
            if line.startswith("$$") and not line.endswith("$$"):
                return False  # another one's opening
            if line.endswith("$$"):
                break
    if silent:
        return True
    state.line = nxt + 1
    token = state.push("math_block", "math", 0)
    token.block = True
    lines = state.getLines(start, state.line, state.blkIndent, False)
    token.content = lines.strip()[2:-2]
    token.markup = "$$"
    token.map = [start, state.line]
    return True


def _amsmath(state: StateBlock, start: int, end: int, silent: bool) -> bool:
    """\\begin{env} at a line's start, to the line that ends \\end{env} (mathrules.ts
    amsmath)."""
    if state.sCount[start] - state.blkIndent >= 4:
        return False
    if not (m := AMS_OPEN.match(_line(state, start))):
        return False
    closing = rf"\end{{{m[1]}{m[2]}}}"
    for nxt in range(start, end):
        line = _line(state, nxt)
        if line.rstrip().endswith(closing):
            if silent:
                return True
            state.line = nxt + 1
            token = state.push("amsmath", "math", 0)
            token.block = True
            token.content = state.getLines(
                start, state.line, state.sCount[start], False
            )
            token.meta = {"environment": m[1], "numbered": m[2]}
            token.map = [start, state.line]
            return True
        if nxt == start or not line.strip():
            continue
        if state.sCount[nxt] < state.blkIndent:
            return False  # out of a list item
        if (again := AMS_OPEN.match(line)) and again[0] == m[0]:
            return False  # another one's opening
    return False


def maths_plugin(md: MarkdownIt) -> None:
    md.use(dollarmath_plugin)
    md.inline.ruler.at("math_inline", _inline)
    md.block.ruler.at("math_block", _block)
    md.use(amsmath_plugin)
    md.block.ruler.at("amsmath", _amsmath, {"alt": AMS_ALT})
