"""Page text parsed as Markdown (markdown-it-py: CommonMark, plus GFM tables,
strikethrough and footnotes, Obsidian's [[target|label]] links, and maths: maths.py), as
the PWA renders it with markdown-it: raw HTML is text, a line break stays one. Used for
the text the search index holds (`plain`) and for link rewriting (`rewrite`), so code
is never mistaken for a link, and no part of it backtracks on hostile text."""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from typing import Literal
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline
from markdown_it.rules_inline import image as image_rule
from markdown_it.rules_inline import link as link_rule
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin

from .maths import maths_plugin
from .public import origin

__all__ = [
    "Link",
    "page_path",
    "plain",
    "rewrite",
    "wiki_link",
    "wiki_page",
    "wiki_parts",
    "wiki_targets",
]

Rule = Callable[[StateInline, bool], bool]
# A page's slug, fullmatch: render.ts WIKI's slug part, before any #. [[slug#heading]]
# links to the page (wiki_page) everywhere: the PWA, downloads, exports, links and
# backlinks; the #heading is dropped, as the PWA does not yet scroll to another page's.
SLUG = re.compile(r"[a-z0-9-]+")
PAGE_PATH = re.compile(rf"/p/({SLUG.pattern})")  # a page's path (PAGE), fullmatch


def _wiki(state: StateInline, silent: bool) -> bool:
    """[[target]], [[target|label]] and ![[target]] (an embed): no brackets or line
    break inside. Each scan stops at the next bracket, so text is read once."""
    src, pos, end = state.src, state.pos, state.posMax
    embed = src.startswith("!", pos)
    start = pos + embed
    if not src.startswith("[[", start):
        return False
    close = start + 2
    while close < end and src[close] not in "[]\n":
        close += 1
    if close == start + 2 or not src.startswith("]]", close):
        return False
    if not silent:
        token = state.push("wiki", "", 0)
        token.content = src[start + 2 : close]
        token.markup = "!" if embed else ""
        token.meta = {"start": pos, "end": close + 2}
    state.pos = close + 2
    return True


def _spanned(rule: Rule) -> Rule:
    """A link or image rule that also notes where its token's source starts and ends,
    and its raw label (from the inline text the rule was given)."""

    def spanned(state: StateInline, silent: bool) -> bool:
        start, count = state.pos, len(state.tokens)
        if not rule(state, silent):
            return False
        if not silent and len(state.tokens) > count:
            bracket = start + (state.src[start] == "!")
            end = state.md.helpers.parseLinkLabel(state, bracket, False)
            label = state.src[bracket + 1 : end] if end >= 0 else ""
            opened = next(
                t for t in state.tokens[count:] if t.type in ("link_open", "image")
            )  # after any text that was pending
            opened.meta = {"start": start, "end": state.pos, "label": label}
        return True

    return spanned


@cache
def parser() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "breaks": True})
    md.enable(["table", "strikethrough"])
    md.use(footnote_plugin)
    md.use(maths_plugin)
    md.inline.ruler.at("link", _spanned(link_rule))
    md.inline.ruler.at("image", _spanned(image_rule))
    md.inline.ruler.before("link", "wiki", _wiki)
    return md


def wiki_parts(inner: str) -> tuple[str, str]:
    """A wiki link's target and label ("" if none); a table cell escapes its pipe."""
    target, _, label = inner.replace("\\|", "|").partition("|")
    return target.strip(), label.strip()


def wiki_page(target: str) -> str:
    """The page a wiki link's target names: its part before any #heading, or the
    target as typed if that part is empty ([[#heading]], no page). A slug only if
    SLUG matches it; any other is a link the PWA draws as plain text.

    >>> wiki_page("a-page#intro"), wiki_page("a-page"), wiki_page("#intro")
    ('a-page', 'a-page', '#intro')
    """
    return target.split("#")[0].strip() or target


def page_path(href: str, origins: Iterable[str] = ()) -> str | None:
    """The slug a link's address names a page here by, else None: /p/<slug> as a path
    (`/p/<slug>`) or on one of origins (a full address, `https://<host>/p/<slug>`, as
    a model writes one), either with any query or #heading after it. These are the
    links the PWA opens in place (render.ts: inline() for a path, own() for a full
    address)."""
    if href.startswith("/p/"):
        path = urlsplit(href).path
    elif (here := origin(href)) is not None and here in origins:
        path = urlsplit(href).path
    else:
        return None
    m = PAGE_PATH.fullmatch(path)
    return m[1] if m else None


def wiki_targets(text: str, origins: Iterable[str] = ()) -> list[str]:
    """The targets of a text's page links, each once in order: [[target]] and
    [[target|label]] (a [[slug#heading]]'s is slug: wiki_page), and a Markdown link or
    <autolink> to /p/<slug>, as a path or on one of origins (page_path); not an embed
    (![[...]], an image), and none in code.
    Any [[...]] the parser takes as a page link counts, including forms the PWA draws
    as plain text ([[Some Title]]), so has:dangling finds links that don't work."""
    if "[[" not in text and "/p/" not in text:  # most pages: no parse
        return []
    origins = tuple(origins)
    found: dict[str, None] = {}
    for t in parser().parse(text):
        for c in t.children or []:
            if c.type == "wiki" and not c.markup:
                target = wiki_page(wiki_parts(c.content)[0])
            elif c.type == "link_open":
                target = page_path(str(c.attrGet("href") or ""), origins)
            else:
                continue
            if target:
                found[target] = None
    return list(found)


# Inline tokens whose content is words to search: text, code and maths (its TeX)
TEXT = ("text", "text_special", "code_inline", "math_inline", "math_inline_double")


def _text(children: list[Token]) -> str:
    out: list[str] = []
    for t in children:
        if t.type in TEXT:
            out.append(t.content)
        elif t.type in ("softbreak", "hardbreak"):
            out.append("\n")
        elif t.type == "image":
            out.append(_text(t.children or []))
        elif t.type == "wiki":
            target, label = wiki_parts(t.content)
            out.append(label or target)
    return "".join(out)


def plain(text: str) -> str:
    """Text as words to search: link and image text but not their addresses, a page
    link's label (else its target), code as typed, a table's cells, no markup."""
    out: list[str] = []
    for t in parser().parse(text):
        if t.type == "inline":
            out.append(_text(t.children or []))
        elif t.type in ("fence", "code_block", "math_block", "amsmath"):
            out.append(t.content)
        elif t.type in ("th_close", "td_close"):
            out.append(" ")
        elif t.nesting == -1 or t.type == "hr":
            out.append("\n")
    return "".join(out).strip()


@dataclass
class Link:
    kind: Literal["wiki", "link", "image"]
    # a wiki link's inner text (split it with wiki_parts), else the address
    # (percent-encoded)
    target: str
    label: str  # as typed: a wiki link's label, a link's text, an image's alt text
    embed: bool  # an image, or ![[target]]
    in_table: bool  # in a table cell: a pipe must be escaped


def _lines(text: str) -> list[int]:
    """Where each line of text starts, and the end."""
    starts = [0]
    for i, c in enumerate(text):
        if c == "\n":
            starts.append(i + 1)
    starts.append(len(text) + 1)
    return starts


def _source(
    block: Token, text: str, starts: list[int], cursor: dict[int, int]
) -> Callable[[int], int] | None:
    """Maps an offset in an inline block's text to one in the page's text. Its lines
    are the page's lines from block.map on, less what the parser cut from their start
    (indents, a list item's or quote's markers) or a table cell's ends; cursor is where
    the last cell found on a line ended. None if a line is not found as it is (a tab the
    parser expanded)."""
    if block.map is None:
        return None
    where: list[tuple[int, int, int, list[int]]] = []  # offset, indent, page offset,
    at = 0  # and where the page escaped a pipe the parser unescaped (in a table cell)
    for line, part in enumerate(block.content.split("\n"), start=block.map[0]):
        if line >= len(starts) - 1:
            return None
        lead = len(part) - len(part.lstrip())
        typed, pipes = part[lead:], []
        begin, stop = starts[line] + cursor.get(line, 0), starts[line + 1]
        found = text.find(typed, begin, stop)
        if found < 0 and "|" in typed:
            typed = typed.replace("|", "\\|")
            found = text.find(typed, begin, stop)
            pipes = [i for i, c in enumerate(part[lead:]) if c == "|"]
        if found < 0:
            return None
        cursor[line] = found + len(typed) - starts[line]
        where.append((at, lead, found, pipes))
        at += len(part) + 1

    begins = [w[0] for w in where]

    def source(offset: int) -> int:  # a binary search: no line is looked at twice
        at = bisect_right(begins, offset) - 1
        if at < 0:
            return offset
        begin, lead, found, pipes = where[at]
        col = max(offset - begin - lead, 0)
        return found + col + bisect_left(pipes, col)

    return source


def _spans(tokens: list[Token], table: bool) -> Iterator[tuple[int, int, Link]]:
    for t in tokens:
        if "start" not in t.meta:
            continue
        start, end = t.meta["start"], t.meta["end"]
        if t.type == "wiki":
            embed = bool(t.markup)
            yield start, end, Link("wiki", t.content, "", embed, table)
        elif t.type in ("link_open", "image"):
            href = str(t.attrGet("href" if t.type == "link_open" else "src") or "")
            kind: Literal["link", "image"] = "image" if t.type == "image" else "link"
            yield start, end, Link(kind, href, t.meta["label"], kind == "image", table)


def rewrite(
    text: str,
    replace: Callable[[Link], str | None],
    unmapped: Callable[[int], None] = lambda line: None,
) -> str:
    """text with each link, image and wiki link outside code replaced by what replace
    returns for it (None: kept as typed), in the order they appear. A link whose text
    holds a bracket is kept, and what is inside it is replaced instead; one spanning
    lines is kept. A block whose lines can't be found as the parser saw them (a tab
    it expanded) is kept whole: unmapped is told its first line (from 1)."""
    md = parser()
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\0", "\ufffd")
    starts = _lines(text)
    found: list[tuple[int, int, Link]] = []
    cursor: dict[int, int] = {}
    table = False
    for block in md.parse(text):
        if block.type in ("table_open", "table_close"):
            table = block.type == "table_open"
        if block.type != "inline" or not block.children:
            continue
        source = _source(block, text, starts, cursor)
        if source is None:
            if any("start" in t.meta for t in block.children):
                unmapped((block.map or [0])[0] + 1)
            continue
        for start, end, link in _spans(block.children, table):
            raw = block.content[start:end]
            s, e = source(start), source(end - 1) + 1
            if "\n" in raw or text[s:e].replace("\\|", "|") != raw.replace("\\|", "|"):
                continue  # across lines, or not where it was looked for
            found.append((s, e, link))
    out: list[str] = []
    done = 0
    for s, e, link in sorted(found, key=lambda f: (f[0], -f[1])):
        if s < done:
            continue  # inside a link already replaced
        if link.kind == "link" and ("[" in link.label or "]" in link.label):
            continue
        new = replace(link)
        if new is None:
            continue
        out += [text[done:s], new]
        done = e
    out.append(text[done:])
    return "".join(out)


def wiki_link(link: Link, href: Callable[[str], str]) -> str | None:
    """A [[slug]] or [[slug|label]] link (to a #heading too) as a Markdown link to
    href(slug); None (kept as typed) for any other link, an embed, or a target the PWA
    shows as plain text, whose part before any # is not a slug ([[Some Title]],
    [[#heading]]). A bracket in the label becomes a parenthesis, and in a table cell
    its pipes are escaped, since a bare one would end the cell.

    >>> wiki = Link("wiki", "a-page#intro|Intro", "", embed=False, in_table=False)
    >>> wiki_link(wiki, lambda slug: f"/p/{slug}")
    '[Intro](/p/a-page)'
    """
    if link.kind != "wiki" or link.embed:
        return None
    target, label = wiki_parts(link.target)
    slug = wiki_page(target)
    if not SLUG.fullmatch(slug):
        return None
    label = (label or target).replace("[", "(").replace("]", ")")
    if link.in_table:
        label = label.replace("|", "\\|")
    return f"[{label}]({href(slug)})"


TASK = re.compile(r"\[([ xX])\](?: |$)")
# A list item's first line: quote markers, a bullet or number, then a task marker (as
# tasks.ts ITEM, which ticks it there)
ITEM = re.compile(r"(?:[ \t]*>)*[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+\[[ xX]\]")


def tasks(text: str) -> tuple[int, int]:
    """A page's task boxes (- [ ] and - [x]) exactly as the PWA draws them (render.ts
    task): a list item whose paragraph's first text (escapes and all, as parsed)
    starts with the marker, and whose first line in the text holds it as typed (so
    the PWA can tick it). One in code, a quote's text, a heading, escaped (\\[ ]) or
    a link named [x] is none. Returns (ticked, all)."""
    tokens = parser().parse(text)
    source = re.split(r"\r\n?|\n", text)  # markdown-it's lines (its normalize)
    done = total = 0
    for i, t in enumerate(tokens):
        item = tokens[i - 2] if i >= 2 else None
        first = t.children[0] if t.children else None
        if (
            item is not None
            and t.type == "inline"
            and tokens[i - 1].type == "paragraph_open"
            and item.type == "list_item_open"
            and item.map
            and first is not None
            and first.type == "text"
            and (m := TASK.match(first.content))
            and ITEM.match(source[item.map[0]])
        ):
            total += 1
            done += m[1] != " "
    return done, total
