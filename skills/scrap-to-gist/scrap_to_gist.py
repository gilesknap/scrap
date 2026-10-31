#!/usr/bin/env python3
"""Convert a scrap page's Markdown body into GitHub-gist Markdown that looks like scrap.

Usage: scrap_to_gist.py IN.md OUT.md [--title "H1 title"] [--scrap-host URL]
                        [--link slug=https://...]...
       scrap_to_gist.py --check GIST.md API.html

Maths is found with scrap's own rules (ported from src/scrap/maths.py and
web/src/mathrules.ts, the cases in tests/maths_cases.json): $...$ and $$...$$ in a
line, $$ ... $$ on lines of their own, a top-level amsmath environment, and ```math
fences. Code (inline code spans, ``` and ~~~ fences, indented code) is never changed.

Transforms (all idempotent, so re-running on its own output is safe):
  * [[slug|label]] / [[slug]] (and [[slug\\|label]] in a table) -> [label](URL):
    --link slug=URL wins, else the scrap page URL (--scrap-host, default $SCRAP_URL;
    needed only when a link uses it)
  * display maths ($$ blocks, amsmath environments, ```math fences; centred in scrap)
    -> a ```math block that starts \\Large, followed by an &nbsp; paragraph
  * a line that is only "$\\displaystyle ...$" -> $`\\displaystyle\\Large ...`$
    (left-aligned, as in scrap)
  * other inline $...$ -> $`\\large ...`$, and $$...$$ within a line ->
    $`\\displaystyle\\Large ...`$
  * a $ that scrap does not read as maths ("$5 and $10") -> \\$, so GitHub leaves it
  * <br> above and below each "---" divider that precedes a heading
  * optional "# title" prepended (scrap keeps the title outside the body)
Maths using \\cancel is reported on stderr: GitHub does not draw it, so swap in an
image (see SKILL.md).

--check reads the HTML of GitHub's markdown API for GIST.md and reports maths GitHub
did not recognise (it would show as raw text). Only the standard library is used.
"""

import argparse
import html
import os
import re
import sys

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


def _escaped(src: str, pos: int) -> bool:
    """Whether the character at pos is escaped: an odd run of backslashes before it."""
    n = 0
    while pos - n - 1 >= 0 and src[pos - n - 1] == "\\":
        n += 1
    return n % 2 == 1


def _math_at(src: str, pos: int) -> tuple[str, bool, int] | None:
    """$tex$ or $$tex$$ starting at pos, as scrap reads it (maths.py _inline):
    (tex, double, end after the closing $), else None. Money is not maths: an opening
    $ is not followed by a space nor preceded by a digit, a closing $ not preceded by
    a space nor followed by a digit."""

    def digit(i: int) -> bool:
        return 0 <= i < len(src) and src[i].isdigit() and src[i].isascii()

    if src[pos] != "$" or pos + 1 >= len(src) or digit(pos - 1) or _escaped(src, pos):
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
        if _escaped(src, end) or (double and src[end + 1 : end + 2] != "$"):
            start = end + 1
        else:
            break
    tex = src[pos + width : end]
    if not tex or (not double and src[end - 1].isspace()) or digit(end + width):
        return None
    return tex, double, end + width


# --- blocks ---------------------------------------------------------------------------

QUOTE = re.compile(r"(?: {0,3}>[ ]?)*")
LIST = re.compile(r" {0,3}(?:[-*+]|\d{1,9}[.)])(?: +|$)")
FENCE = re.compile(r"(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r" {0,3}#{1,6}(?:\s|$)")
TABLE_DELIM = re.compile(r"\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
CODE = "\x00{}\x00"  # a placeholder line for a code block, put back at the end


def _quote(line: str) -> str:
    """The quote markers at the start of line ("" if none)."""
    m = QUOTE.match(line)
    return m[0] if m else ""


def _width(s: str) -> int:
    return len(s.expandtabs(4))


def _split(line: str) -> tuple[str, str]:
    """(container prefix, text): the quote markers, a list marker and indent."""
    q = _quote(line)
    rest = line[len(q) :]
    m = LIST.match(rest)
    if m:
        return line[: len(q) + m.end()], rest[m.end() :]
    indent = len(rest) - len(rest.lstrip(" \t"))
    return line[: len(q) + indent], rest[indent:]


def _quotes(line: str) -> int:
    return _quote(line).count(">")


def _cont(prefix: str) -> str:
    """The prefix for the following lines of a block that starts after prefix."""
    q = _quote(prefix)
    return q + " " * _width(prefix[len(q) :])


def _inner(cont: str) -> int:
    """The indent a block's following lines need (its list item's), after quotes."""
    return _width(cont) - _width(_quote(cont))


def _strip(line: str, cont: str) -> str:
    """line without its container prefix (quote markers, then up to cont's indent)."""
    q = _quote(line)
    rest = line[len(q) :]
    want = _inner(cont)
    n = 0
    while n < len(rest) and rest[n] == " " and n < want:
        n += 1
    return rest[n:]


def _indent(line: str) -> int:
    """The indent of line after its quote markers."""
    rest = line[len(_quote(line)) :]
    return _width(rest) - _width(rest.lstrip(" \t"))


def _blank(line: str) -> bool:
    return not line[len(_quote(line)) :].strip()


def protect_code(lines: list[str]) -> tuple[list[str], list[str]]:
    """Swap each code block (non-math fence, indented code) for a placeholder line.
    ```math fences stay: they are display maths in scrap."""
    out: list[str] = []
    saved: list[str] = []
    i, in_list, prev_blank = 0, False, True
    while i < len(lines):
        line = lines[i]
        prefix, text = _split(line)
        if _blank(line):
            out.append(line)
            i += 1
            prev_blank = True
            continue
        if LIST.match(line[len(_quote(line)) :]):
            in_list = True
        elif prev_blank and not line[:1].isspace():
            in_list = False
        if prev_blank and not in_list and _indent(line) >= 4:
            j = i
            while j < len(lines) and (_blank(lines[j]) or _indent(lines[j]) >= 4):
                j += 1
            while _blank(lines[j - 1]):
                j -= 1
            saved.append("\n".join(lines[i:j]))
            out.append(CODE.format(len(saved) - 1))
            i, prev_blank = j, False
            continue
        if (m := FENCE.match(text)) and (in_list or _indent(line) < 4):
            mark, info = m[1], m[2].strip()
            if not (mark[0] == "`" and "`" in info):
                cont = _cont(prefix)
                j = i + 1
                while j < len(lines):
                    close = _strip(lines[j], cont).strip()
                    if close.startswith(mark) and not close.strip(mark[0]):
                        break
                    j += 1
                if info.split()[:1] != ["math"]:
                    saved.append("\n".join(lines[i : j + 1]))
                    out.append(CODE.format(len(saved) - 1))
                else:
                    out.extend(lines[i : j + 1])
                i, prev_blank = j + 1, False
                continue
        out.append(line)
        i += 1
        prev_blank = False
    return out, saved


# --- inline -------------------------------------------------------------------------


class Converter:
    def __init__(self, links: dict[str, str], scrap_host: str | None):
        self.links = links
        self.host = scrap_host
        self.maths: list[str] = []

    def link(self, slug: str) -> str:
        if slug in self.links:
            return self.links[slug]
        if not self.host:
            sys.exit(
                f"[[{slug}]] needs the scrap address: pass --scrap-host or set "
                f"SCRAP_URL (or --link {slug}=URL)"
            )
        return f"{self.host}/p/{slug}"

    def inline_math(self, tex: str, kind: str) -> str:
        self.maths.append(tex)
        if kind == "line":  # the whole line: left-aligned display maths in scrap
            tex = re.sub(
                r"^\\displaystyle(?![A-Za-z])\s*(?:\\(?:large|Large)(?![A-Za-z])\s*)?",
                "",
                tex,
            )
            body = "\\displaystyle\\Large " + tex
        elif kind == "double":  # $$...$$ in a line: display maths, kept in the line
            body = "\\displaystyle\\Large " + tex.strip()
        else:
            body = "\\large " + re.sub(r"^\\(?:large|Large)(?![A-Za-z])\s*", "", tex)
        if "`" in body:  # cannot go in $`...`$
            return f"${tex}$"
        return f"$`{body}`$"

    def inline(self, src: str, wiki: bool = True) -> str:
        """Convert maths and links in text; code spans are copied as they are."""
        out: list[str] = []
        i, n = 0, len(src)
        while i < n:
            c = src[i]
            if c == "\\" and i + 1 < n and src[i + 1] in PUNCT:
                out.append(src[i : i + 2])
                i += 2
            elif c == "`":
                run = len(src[i:]) - len(src[i:].lstrip("`"))
                m = re.compile(rf"(?<!`)`{{{run}}}(?!`)").search(src, i + run)
                end = m.end() if m else i + run
                out.append(src[i:end])
                i = end
            elif c == "$" and (m := re.compile(r"\$(`+)(.+?)\1\$").match(src, i)):
                self.maths.append(m[2])  # already GitHub's form
                out.append(m[0])
                i = m.end()
            elif c == "$":
                found = _math_at(src, i)
                if not found:
                    out.append("$" if _escaped(src, i) else "\\$")
                    i += 1
                    continue
                tex, double, end = found
                start = src.rfind("\n", 0, i) + 1
                stop = src.find("\n", end)
                stop = n if stop < 0 else stop
                whole = (
                    not double
                    and not _split(src[start:i])[1]
                    and not src[end:stop].strip()
                    and re.match(r"\\displaystyle(?![A-Za-z])", tex)
                )
                kind = "line" if whole else "double" if double else "inline"
                out.append(self.inline_math(tex, kind))
                i = end
            elif wiki and src.startswith("[[", i):
                end = i + 2
                while end < n and src[end] not in "[]\n":
                    end += 1
                m = src.startswith("]]", end) and WIKI.match(src[i + 2 : end])
                if not m:
                    out.append("[")
                    i += 1
                    continue
                label = self.inline(m[2], wiki=False) if m[2] else m[1]
                out.append(f"[{label}]({self.link(m[1])})")
                i = end + 2
            else:
                out.append(c)
                i += 1
        return "".join(out)

    def table_row(self, line: str) -> str:
        """A table row, cell by cell: scrap reads each cell's text on its own."""
        cells, start, i = [], 0, 0
        while i < len(line):
            if line[i] == "\\":
                i += 2
                continue
            if line[i] == "|":  # an escaped \| (as in [[slug\|label]]) was skipped
                cells.append(line[start:i])
                start = i + 1
            i += 1
        cells.append(line[start:])
        return "|".join(self.inline(c) for c in cells)

    # --- blocks ---

    def math_block(self, tex: str, cont: str) -> list[str]:
        tex = re.sub(r"^\s*\\(?:large|Large)(?![A-Za-z])\s*", "", tex)
        self.maths.append(tex)
        lines = ["\\Large", *tex.rstrip().split("\n")]
        return [cont + x if x else cont.rstrip() for x in lines] + [cont + "```"]

    def blocks(self, lines: list[str]) -> list[str]:
        out: list[str] = []
        para: list[str] = []

        def flush() -> None:
            if not para:
                return
            if len(para) > 1 and "|" in para[0] and TABLE_DELIM.match(para[1]):
                out.extend(self.table_row(x) for x in para)
            else:
                out.extend(self.inline("\n".join(para)).split("\n"))
            para.clear()

        i = 0
        while i < len(lines):
            line = lines[i]
            prefix, text = _split(line)
            stripped = text.strip()
            block: tuple[str, str, int] | None = None  # (tex, first prefix, next line)
            if re.fullmatch("\x00\\d+\x00", line):
                flush()
                out.append(line)
                i += 1
                continue
            if (m := FENCE.match(text)) and m[2].strip().split()[:1] == ["math"]:
                cont, mark = _cont(prefix), m[1]
                j = i + 1
                body = []
                while j < len(lines):
                    t = _strip(lines[j], cont)
                    if t.strip().startswith(mark) and not t.strip().strip(mark[0]):
                        break
                    body.append(t)
                    j += 1
                block = ("\n".join(body), prefix, j + 1)
            elif stripped.startswith("$$") and not para:
                block = self.dollar_block(lines, i, prefix, stripped)
            elif AMS_OPEN.match(text):
                block = self.ams_block(lines, i, prefix, text)
            if block:
                flush()
                tex, first, j = block
                cont = _cont(first)
                out.append(first + "```math")
                out.extend(self.math_block(tex, cont))
                # exactly one &nbsp; spacer paragraph after every math block
                nbsp = False
                while j < len(lines) and (
                    _blank(lines[j])
                    or (not nbsp and _strip(lines[j], cont).strip() == "&nbsp;")
                ):
                    nbsp = nbsp or not _blank(lines[j])
                    j += 1
                out.extend([cont.rstrip(), cont + "&nbsp;", cont.rstrip()])
                i = j
                continue
            if _blank(line) or HEADING.match(text):
                flush()
                out.append(self.inline(line) if not _blank(line) else line)
            else:
                para.append(line)
            i += 1
        flush()
        return out

    def dollar_block(
        self, lines: list[str], i: int, prefix: str, first: str
    ) -> tuple[str, str, int] | None:
        """$$ at a line's start, to a line that ends $$ (that one, if it is more than
        $$), with no blank line between (maths.py _block). One line holding more than
        one formula ("$$a$$ and $$b$$") is left to the inline rule."""
        cont = _cont(prefix)
        if len(first) > 3 and first.endswith("$$"):
            if "$" in first[2:-2]:
                return None
            return first[2:-2], prefix, i + 1
        j = i
        while True:
            j += 1
            if j >= len(lines):
                return None
            t = _strip(lines[j], cont)
            line = t.strip()
            out_of_list = _indent(lines[j]) < _width(cont) - _width(_quote(cont))
            if not line or out_of_list or _quotes(lines[j]) != _quotes(prefix):
                return None  # a blank line, or out of the list item or quote
            if line.startswith("$$") and not line.endswith("$$"):
                return None  # another one's opening
            if line.endswith("$$"):
                break
        body = [first] + [_strip(x, cont) for x in lines[i + 1 : j + 1]]
        return "\n".join(body).strip()[2:-2].strip("\n"), prefix, j + 1

    def ams_block(
        self, lines: list[str], i: int, prefix: str, text: str
    ) -> tuple[str, str, int] | None:
        """\\begin{env} at a line's start, to the line that ends \\end{env}
        (maths.py _amsmath)."""
        m = AMS_OPEN.match(text)
        if not m:
            return None
        closing = rf"\end{{{m[1]}{m[2]}}}"
        cont = _cont(prefix)
        for j in range(i, len(lines)):
            t = text if j == i else _strip(lines[j], cont)
            if t.rstrip().endswith(closing):
                body = [text] + [_strip(x, cont) for x in lines[i + 1 : j + 1]]
                return "\n".join(body), prefix, j + 1
            if j == i or not t.strip():
                continue
            if (again := AMS_OPEN.match(t)) and again[0] == m[0]:
                return None
        return None


def convert(
    s: str, links: dict[str, str], scrap_host: str | None
) -> tuple[str, list[str]]:
    """Return the gist Markdown for the scrap Markdown s, and the maths found."""
    lines, saved = protect_code(s.replace("\r\n", "\n").split("\n"))
    s = "\n".join(lines)
    # scrap pages often pad dividers with &nbsp; paragraphs; the divider step re-adds
    # spacing ("---" after a blank line: after text it underlines a heading)
    s = re.sub(r"(?:(?<=\n\n)|\A)(?:&nbsp;\n\n)?---\n\n(?:&nbsp;\n\n)?", "---\n\n", s)
    c = Converter(links, scrap_host)
    s = "\n".join(c.blocks(s.split("\n")))
    # breathing space round dividers before headings
    s = re.sub(
        r"(?<=\n)(?:\n<br>\n)?\n---\n\n(?:<br>\n\n)?(#)",
        r"\n<br>\n\n---\n\n<br>\n\n\1",
        s,
    )
    s = re.sub("\x00(\\d+)\x00", lambda m: saved[int(m[1])], s)
    return s.rstrip("\n") + "\n", c.maths


def check(md: str, page: str) -> int:
    """Compare the maths in md with what GitHub's markdown API recognised in page."""
    _, maths = convert(md, {}, "x")
    found = len(re.findall(r"<math-renderer", page))
    rest = re.sub(r"<math-renderer.*?</math-renderer>", "", page, flags=re.S)
    rest = re.sub(r"<pre.*?</pre>", "", rest, flags=re.S)
    raw = re.findall(r"\$<code>.*?</code>\$", rest)
    rest = re.sub(r"<code>.*?</code>", "", rest, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "", rest))
    raw += re.findall(r"\\[A-Za-z]+[^\n]{0,30}", text)
    print(f"{found} maths recognised by GitHub, {len(maths)} in the markdown")
    for r in raw:
        print(f"raw maths: {html.unescape(r)}")
    return 0 if found == len(maths) and not raw else 1


def main() -> None:
    p = argparse.ArgumentParser(
        description="Convert a scrap page body into GitHub-gist Markdown."
    )
    p.add_argument("inp")
    p.add_argument("out")
    p.add_argument("--title")
    p.add_argument(
        "--scrap-host",
        default=os.environ.get("SCRAP_URL"),
        help="address scrap is served at, for [[slug]] links (default: $SCRAP_URL)",
    )
    p.add_argument("--link", action="append", default=[], help="slug=URL")
    p.add_argument(
        "--check",
        action="store_true",
        help="IN.md is the gist Markdown, OUT the markdown API's HTML of it: report "
        "maths GitHub left as raw text",
    )
    a = p.parse_args()

    with open(a.inp, encoding="utf-8") as f:
        src = f.read()
    if a.check:
        with open(a.out, encoding="utf-8") as f:
            sys.exit(check(src, f.read()))
    links = dict(x.split("=", 1) for x in a.link)
    host = a.scrap_host.rstrip("/").removesuffix("/mcp") if a.scrap_host else None
    s, maths = convert(src, links, host)
    if a.title and not s.lstrip().startswith("# "):
        s = f"# {a.title}\n\n{s.lstrip()}"
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(s)
    for tex in maths:
        if "\\cancel" in tex:
            first = tex.strip().split("\n")[0][:60]
            print(
                f"warning: maths uses \\cancel (GitHub does not draw it): {first}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
