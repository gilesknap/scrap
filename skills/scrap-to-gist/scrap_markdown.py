"""scrap's Markdown, read as scrap reads it, for scrap_to_gist.py: its maths rules
(ported from src/scrap/maths.py and web/src/mathrules.ts in the scrap repository, the
cases in tests/maths_cases.json) and the block structure the conversion needs (quotes,
list items, fences, indented code). Only the standard library is used."""

import re

# --- scrap's maths rules (src/scrap/maths.py, web/src/mathrules.ts) ----------------

# The top-level environments scrap takes (mdit_py_plugins.amsmath ENVIRONMENTS)
ENVS = (
    "equation|multline|gather|align|alignat|flalign|matrix|pmatrix|bmatrix|Bmatrix"
    "|vmatrix|Vmatrix|eqnarray"
)
AMS_OPEN = re.compile(rf"\\begin\{{({ENVS})(\*?)\}}")
# [[slug]] / [[slug|label]] / [[slug\|label]] (web/src/render.ts WIKI)
WIKI = re.compile(r"^([a-z0-9-]+)(?:\\?\|(.+))?$")
PUNCT = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")


def escaped(src: str, pos: int) -> bool:
    """Whether the character at pos is escaped: an odd run of backslashes before it."""
    n = 0
    while pos - n - 1 >= 0 and src[pos - n - 1] == "\\":
        n += 1
    return n % 2 == 1


def math_at(src: str, pos: int) -> tuple[str, bool, int] | None:
    """$tex$ or $$tex$$ starting at pos, as scrap reads it (maths.py _inline):
    (tex, double, end after the closing $), else None. Money is not maths: an opening
    $ is not followed by a space nor preceded by a digit, a closing $ not preceded by
    a space nor followed by a digit."""

    def digit(i: int) -> bool:
        return 0 <= i < len(src) and src[i].isdigit() and src[i].isascii()

    if src[pos] != "$" or pos + 1 >= len(src) or digit(pos - 1) or escaped(src, pos):
        return None
    double = src[pos + 1] == "$"
    if not double and src[pos + 1].isspace():
        return None
    width = 2 if double else 1
    start = pos + width
    while True:  # to the closing $ (or $$)
        end = src.find("$", start)
        if end < 0 or end + width > len(src):
            return None
        if escaped(src, end) or (double and src[end + 1 : end + 2] != "$"):
            start = end + 1
        else:
            break
    tex = src[pos + width : end]
    if not tex or (not double and src[end - 1].isspace()) or digit(end + width):
        return None
    return tex, double, end + width


# --- blocks ---------------------------------------------------------------------------

QUOTE = re.compile(r"(?: {0,3}>[ ]?)*")
LIST = re.compile(r"(?: {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]+|$))+")
FENCE = re.compile(r"(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r" {0,3}#{1,6}(?:\s|$)")
TABLE_DELIM = re.compile(r"\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
HR = re.compile(r" {0,3}(?:(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
SETEXT = re.compile(r" {0,3}(?:=+|-+)[ \t]*$")
AUTOLINK = re.compile(
    r"<[A-Za-z][A-Za-z0-9+.\-]{1,31}:[^\s<>]*>"  # a URL
    r"|<[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*>"  # an email address
)
LINK_DEST = re.compile(
    r"\]\((?:<[^>\n]*>|[^\s()<]*(?:\([^\s()]*\)[^\s()<]*)*)"
    r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\)"
)
# \large or \Large, as a whole command, and the spaces after it
SIZE = r"(?![A-Za-z])[ \t]*(?:\\(?:large|Large)(?![A-Za-z])[ \t]*)?"
# The $`...`$ this script writes, kept as it is on a second run
GITHUB_FORM = re.compile(r"\$`(\\(?:large|displaystyle\\Large) [^`]*)`\$")
# A bare URL running up to a position (search with endpos there)
URL_BEFORE = re.compile(r"(?:(?:https?|ftp)://|www\.)[^\s<>()\[\]`]*\Z")
# A reference to one of scrap's own files, as a page's text holds it (web/src/render.ts
# IMAGE and FILE): an image at /api/blobs/<sha>/preview?size=N or /api/blobs/<sha>, a
# file at /api/blobs/<sha> or ...?download=1. Matched where a link destination starts.
OWN_BLOB = re.compile(
    r"/api/blobs/([0-9a-f]{64})(?:/preview\?size=\d+|\?download=1)?(?=[\s)>]|$)"
)
# A link reference or footnote definition
DEFINITION = re.compile(r" {0,3}\[[^\]]+\]:")
# A block of HTML this script or the skill wrote (a centred image), kept as it is
OWN_HTML = '<p align="center"><picture>'
# Placeholder lines for a code block and a ```math fence, while the rest is converted
CODE = "\x00{}\x00"
MATH = "\x00M{}\x00"  # (a NUL in the page is read as U+FFFD, as CommonMark does)


def quote(line: str) -> str:
    """The quote markers at the start of line ("" if none)."""
    m = QUOTE.match(line)
    return m[0] if m else ""


def columns(s: str) -> int:
    return len(s.expandtabs(4))


def split_at(line: str, lm: re.Match[str] | None) -> tuple[str, str]:
    """(container prefix, text), with lm the list marker the line starts an item with
    (None: a marker it has is text, as in "2. b" continuing a paragraph)."""
    q = quote(line)
    rest = line[len(q) :]
    if lm:
        return line[: len(q) + lm.end()], rest[lm.end() :]
    indent = len(rest) - len(rest.lstrip(" \t"))
    return line[: len(q) + indent], rest[indent:]


def quotes(line: str) -> int:
    return quote(line).count(">")


def cont_of(prefix: str) -> str:
    """The prefix for the following lines of a block that starts after prefix."""
    q = quote(prefix)
    return q + " " * (columns(prefix) - len(q))  # (q has no tabs)


def inner(cont: str) -> int:
    """The indent a block's following lines need (its list item's), after quotes."""
    return columns(cont) - columns(quote(cont))


def list_indent(prefix: str) -> int:
    """The content indent of the list item prefix starts, else 0."""
    return inner(cont_of(prefix)) if LIST.match(prefix[len(quote(prefix)) :]) else 0


def strip_prefix(line: str, cont: str) -> str:
    """line without its container prefix (cont's quote markers, then up to its
    indent)."""
    rest = line
    for _ in range(quotes(cont)):
        m = re.match(r" {0,3}>[ ]?", rest)
        rest = rest[m.end() :] if m else rest
    want = inner(cont)
    n = 0
    while n < len(rest) and rest[n] == " " and n < want:
        n += 1
    return rest[n:]


def indent_of(line: str) -> int:
    """The indent of line after its quote markers."""
    q = quote(line)
    rest = line[len(q) :]
    lead = rest[: len(rest) - len(rest.lstrip(" \t"))]
    # tabs to the next multiple of 4 columns; the space a > may take can be a tab's
    tab_after_quote = q.endswith(">") and lead.startswith("\t")
    return len((q + lead).expandtabs(4)) - len(q) - tab_after_quote


def blank(line: str) -> bool:
    return not line[len(quote(line)) :].strip()


def dollar_block(
    lines: list[str], i: int, prefix: str, first: str
) -> tuple[str, str, int] | None:
    """$$ at a line's start, to a line that ends $$ (that one, if it is more than
    $$), with no blank line between (maths.py _block). One line holding more than
    one formula ("$$a$$ and $$b$$") is left to the inline rule."""
    cont = cont_of(prefix)
    if len(first) > 3 and first.endswith("$$"):
        if "$" in first[2:-2]:
            return None
        return first[2:-2], prefix, i + 1
    j = i
    while True:
        j += 1
        if j >= len(lines):
            return None
        t = strip_prefix(lines[j], cont)
        line = t.strip()
        out_of_list = indent_of(lines[j]) < list_indent(prefix)
        if not line or out_of_list or quotes(lines[j]) < quotes(prefix):
            return None  # a blank line, or out of the list item or quote
        if line.startswith("$$") and not line.endswith("$$"):
            return None  # another one's opening
        if line.endswith("$$"):
            break
    body = [first] + [strip_prefix(x, cont) for x in lines[i + 1 : j + 1]]
    return "\n".join(body).strip()[2:-2].strip("\n"), prefix, j + 1


def ams_block(
    lines: list[str], i: int, prefix: str, text: str
) -> tuple[str, str, int] | None:
    """\\begin{env} at a line's start, to the line that ends \\end{env}
    (maths.py _amsmath)."""
    m = AMS_OPEN.match(text)
    if not m:
        return None
    closing = rf"\end{{{m[1]}{m[2]}}}"
    cont = cont_of(prefix)
    for j in range(i, len(lines)):
        t = text if j == i else strip_prefix(lines[j], cont)
        if t.rstrip().endswith(closing):
            body = [text] + [strip_prefix(x, cont) for x in lines[i + 1 : j + 1]]
            return "\n".join(body), prefix, j + 1
        if j == i or not t.strip():
            continue
        if indent_of(lines[j]) < list_indent(prefix):
            return None  # out of the list item
        if (again := AMS_OPEN.match(t)) and again[0] == m[0]:
            return None
    return None


# List markers at any indent; list_match() limits the indent
LIST_ANY = re.compile(r"[ \t]*(?:(?:[-*+]|\d{1,9}[.)])(?:[ \t]+|$))+")


def list_match(after: str, list_w: int) -> re.Match[str] | None:
    """The list marker(s) a line (after its quote markers) starts with, if it starts
    an item: indented at most 3 columns past the content of the list item it is in
    (list_w; 0 outside a list). More than that, it is the item's text or code."""
    m = LIST_ANY.match(after)
    lead = after[: len(after) - len(after.lstrip(" \t"))]
    return m if m and columns(lead) <= list_w + 3 else None


def track_list(line: str, list_w: int, in_para: bool) -> tuple[int, re.Match | None]:
    """The content column of the list item line is in, after line, and its marker
    (if it starts an item: in a paragraph, only one that can end it). A line less
    indented than the item's content, not a paragraph's continuation, leaves the
    item, for an outer one or out of the list."""
    after = line[len(quote(line)) :]
    lm = list_match(after, list_w)
    if lm and (not in_para or interrupts(after, list_w)):
        return columns(lm[0]), lm
    if not in_para and indent_of(line) < list_w:
        return indent_of(line), None
    return list_w, None


def interrupts(after: str, list_w: int) -> bool:
    """Whether a line (after its quote markers) starts a list item that can end a
    paragraph: one that is not empty, and outside a list an ordered one only from 1
    (inside one, any sibling or nested item ends the item before)."""
    lm = list_match(after, list_w)
    return bool(
        lm
        and after[lm.end() :].strip()
        and (list_w > 0 or re.match(r" *(?:[-*+]|1[.)])", after))
    )


def protect_code(
    lines: list[str],
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Swap each code block (a fence that is not ```math, indented code) for a CODE
    placeholder line, and each ```math fence (display maths in scrap) for a MATH one.
    Returns the lines, the code blocks' text and the math fences' (prefix, TeX)."""
    out: list[str] = []
    code: list[str] = []
    fences: list[tuple[str, str]] = []
    i, list_w, open_para, depth = 0, 0, False, 0
    while i < len(lines):
        line = lines[i]
        if blank(line):
            out.append(line)
            i += 1
            open_para = False
            continue
        after = line[len(quote(line)) :]
        if open_para and (
            quotes(line) > depth
            or interrupts(after, list_w)
            or (
                TABLE_DELIM.match(lines[i + 1] if i + 1 < len(lines) else "")
                and "|" in line
            )
        ):
            open_para = False  # a new quote or list item ends the paragraph
        if not open_para:
            depth = quotes(line)
        list_w, lm = track_list(line, list_w, open_para)
        if lm:
            gaps = re.findall(r"(?:[-*+]|\d[.)])([ \t]*)", lm[0])
            if max(columns(g) for g in gaps) >= 5 and after[lm.end() :].strip():
                # content 5 or more spaces after a marker is indented code
                code.append(line)
                out.append(CODE.format(len(code) - 1))
                i, open_para = i + 1, False
                continue
        if not open_para and not lm and indent_of(line) >= list_w + 4:
            j = i  # indented code (it cannot interrupt a paragraph)
            while j < len(lines) and (
                blank(lines[j]) or indent_of(lines[j]) >= list_w + 4
            ):
                j += 1
            while blank(lines[j - 1]):
                j -= 1
            code.append("\n".join(lines[i:j]))
            out.append(CODE.format(len(code) - 1))
            i, open_para = j, False
            continue
        prefix, text = split_at(line, lm)
        span = None
        if not open_para and text.strip().startswith("$$"):
            span = dollar_block(lines, i, prefix, text.strip())
        elif AMS_OPEN.match(text) and (indent_of(line) < 4 or LIST.match(after)):
            span = ams_block(lines, i, prefix, text)
        if span:  # display maths: blocks() converts it
            out.extend(lines[i : span[2]])
            i, open_para = span[2], False
            continue
        m = FENCE.match(text)
        if m and not lm and indent_of(line) < list_w:
            list_w = 0  # a fence less indented than the list item is out of it
        if (
            m
            and (lm or indent_of(line) - list_w < 4)
            and not (m[1][0] == "`" and "`" in m[2])
        ):
            mark, cont, depth = m[1], cont_of(prefix), quotes(line)
            j, closed = i + 1, False
            while j < len(lines):
                nxt = lines[j]
                # the fence ends with its container: the quote, or the list item
                if quotes(nxt) < depth or (
                    list_w and not blank(nxt) and indent_of(nxt) < list_w
                ):
                    break
                close = strip_prefix(nxt, cont).strip()
                if close.startswith(mark) and not close.strip(mark[0]):
                    closed = True
                    break
                j += 1
            if m[2].strip().split()[:1] == ["math"]:
                body = "\n".join(strip_prefix(x, cont) for x in lines[i + 1 : j])
                fences.append((prefix, body))
                out.append(MATH.format(len(fences) - 1))
            else:
                code.append("\n".join(lines[i : j + closed]))
                out.append(CODE.format(len(code) - 1))
            i, open_para = j + closed, False
            continue
        out.append(line)
        i += 1
        open_para = bool(text.strip()) and not HEADING.match(text)
    return out, code, fences
