#!/usr/bin/env python3
"""Convert a scrap page's Markdown body into GitHub-gist Markdown that looks like scrap.

Usage: scrap_to_gist.py IN.md OUT.md [--title "H1 title"] [--scrap-host URL]
                        [--link slug=https://...]...
       scrap_to_gist.py --check GIST.md API.html

Maths is found with scrap's own rules (scrap_markdown.py beside this script, ported
from src/scrap/maths.py and web/src/mathrules.ts, the cases in tests/maths_cases.json):
$...$ and $$...$$ in a line, $$ ... $$ on lines of their own, a top-level amsmath
environment, and ```math fences. Code (inline code spans, ``` and ~~~ fences, indented
code) is never changed.
Deliberate differences: a line such as "$$a$$ and $$b$$" is two formulas here, where
scrap reads one block "a$$ and $$b" (which KaTeX cannot draw); and a $ in a bare URL
(https://..., www....) never starts maths, so the link survives.

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
    (not in a URL); a lone backtick -> \\`, so it cannot pair with $`...`$
  * a line break inside a paragraph -> a hard break (a trailing \\), as scrap shows
    it (it renders with breaks: true; a gist does not)
  * <br> above and below each "---" divider that precedes a heading
  * optional "# title" prepended (scrap keeps the title outside the body)
Maths using \\cancel is reported on stderr: GitHub does not draw it, so swap in an
image (see SKILL.md).

--check reads the HTML of GitHub's markdown API (in gfm mode: markdown mode does not
mark maths) for GIST.md and reports maths GitHub did not recognise (it would show as
raw text). Only the standard library is used.
"""

import argparse
import html
import os
import re
import sys

# scrap_markdown.py is beside this script (also when it is loaded by path)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrap_markdown import (  # noqa: E402
    AMS_OPEN,
    AUTOLINK,
    DEFINITION,
    GITHUB_FORM,
    HEADING,
    HR,
    LINK_DEST,
    LIST,
    OWN_HTML,
    PUNCT,
    SETEXT,
    SIZE,
    TABLE_DELIM,
    URL_BEFORE,
    WIKI,
    ams_block,
    blank,
    cont_of,
    dollar_block,
    escaped,
    indent_of,
    interrupts,
    math_at,
    protect_code,
    quote,
    quotes,
    split_prefix,
    strip_prefix,
)

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
            tex = re.sub(rf"^\\displaystyle{SIZE}", "", tex)
            body = "\\displaystyle\\Large " + tex
        elif kind == "double":  # $$...$$ in a line: display maths, kept in the line
            body = "\\displaystyle\\Large " + tex.strip(" \t")
        else:
            body = "\\large " + re.sub(r"^\\(?:large|Large)(?![A-Za-z])[ \t]*", "", tex)
        if "`" in body:  # cannot go in $`...`$: left as it was
            mark = "$$" if kind == "double" else "$"
            return f"{mark}{tex}{mark}"
        return f"$`{body}`$"

    def inline(self, src: str, wiki: bool = True, breaks: bool = False) -> str:
        """Convert maths and links in text; code spans, autolinks and link
        destinations are copied as they are. With breaks, a newline becomes a hard
        break, as scrap shows it (it renders with breaks: true)."""
        out: list[str] = []
        i, n = 0, len(src)
        text = 0  # where the plain text since the last span (maths, code, link) starts
        while i < n:
            c = src[i]
            if c == "\\" and i + 1 < n and src[i + 1] in PUNCT:
                out.append(src[i : i + 2])
                i += 2
            elif c == "`":
                run = len(src[i:]) - len(src[i:].lstrip("`"))
                m = re.compile(rf"(?<!`)`{{{run}}}(?!`)").search(src, i + run)
                if m:
                    out.append(src[i : m.end()])
                    i = text = m.end()
                else:  # a lone run is text: escape it, so it cannot pair with $`...`$
                    out.append("\\`" * run)
                    i += run
            elif c == "<" and (m := AUTOLINK.match(src, i)):
                out.append(m[0])
                i = text = m.end()
            elif c == "<" and re.match(r"[A-Za-z/!?]", src[i + 1 : i + 2]):
                # scrap shows HTML as text (html: false); GitHub would take it as a tag
                out.append("&lt;")
                i += 1
            elif c == "]" and (m := LINK_DEST.match(src, i)):
                out.append(m[0])
                i = text = m.end()
            elif c == "\n" and breaks:
                done = "".join(out)
                last = done[done.rfind("\n") + 1 :]
                trail = len(last) - len(last.rstrip("\\"))
                if not (not last.strip() or last.endswith("  ") or trail % 2):
                    out.append("\\")
                out.append(c)
                i += 1
            elif c == "$" and (m := GITHUB_FORM.match(src, i)):
                self.maths.append(m[1])  # already GitHub's form
                out.append(m[0])
                i = text = m.end()
            elif c == "$":
                if URL_BEFORE.search(src, text, i):  # a $ in a URL stays as it is
                    out.append("$")
                    i += 1
                    continue
                found = math_at(src, i)
                if not found:
                    out.append("$" if escaped(src, i) else "\\$")
                    i += 1
                    continue
                tex, double, end = found
                start = src.rfind("\n", 0, i) + 1
                stop = src.find("\n", end)
                stop = n if stop < 0 else stop
                whole = (
                    not double
                    and not src[start:i].strip()
                    and not src[end:stop].strip()
                    and re.match(r"\\displaystyle(?![A-Za-z])", tex)
                )
                kind = "line" if whole else "double" if double else "inline"
                out.append(self.inline_math(tex, kind))
                i = text = end
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
                i = text = end + 2
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

    def math_block(self, tex: str, first: str, cont: str) -> list[str]:
        # one \Large first (an earlier one dropped), no blank lines round the TeX
        tex = re.sub(r"^[ \t]*\\(?:large|Large)(?![A-Za-z])[ \t]*", "", tex.strip("\n"))
        tex = tex.strip("\n")
        self.maths.append(tex)
        lines = ["\\Large", *(tex.rstrip().split("\n") if tex.strip() else [])]
        # a fence longer than any run of backticks the TeX starts a line with
        runs = [len(x.lstrip()) - len(x.lstrip().lstrip("`")) for x in lines]
        fence = "`" * max([3, *(n + 1 for n in runs if n >= 3)])
        body = [cont + x if x else cont.rstrip() for x in lines]
        return [first + fence + "math", *body, cont + fence]

    def paragraph(self, para: list[tuple[str, str]]) -> list[str]:
        """A paragraph's lines, converted with their prefixes put back."""
        texts = self.inline("\n".join(t for _, t in para), breaks=True).split("\n")
        return [p + t for (p, _), t in zip(para, texts, strict=True)]

    def blocks(self, lines: list[str], fences: list[tuple[str, str]]) -> list[str]:
        out: list[str] = []
        para: list[tuple[str, str]] = []  # a paragraph's lines: (prefix, text)
        depth = 0  # the paragraph's quote depth
        in_list = after_blank = False

        def flush() -> None:
            if not para:
                return
            if len(para) > 1 and "|" in para[0][1] and TABLE_DELIM.match(para[1][1]):
                out.extend(self.table_row(p + t) for p, t in para)
            else:
                out.extend(self.paragraph(para))
            para.clear()

        i = 0
        while i < len(lines):
            line = lines[i]
            if re.fullmatch("\x00\\d+\x00", line):
                flush()
                out.append(line)
                i += 1
                continue
            prefix, text = split_prefix(line)
            stripped = text.strip()
            after = line[len(quote(line)) :]
            was_in_list = in_list
            if blank(line):
                after_blank = True
            else:
                if LIST.match(after):
                    in_list = True
                elif after_blank and not after[:1].isspace():
                    in_list = was_in_list = False
                after_blank = False
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            table = "|" in text and TABLE_DELIM.match(nxt[len(quote(nxt)) :])
            # what ends a paragraph: a blank line, a new quote, a list item that is not
            # empty (outside a list an ordered one only from 1), a heading, a thematic
            # break, a table, a definition
            if para and (
                blank(line)
                or quotes(line) > depth
                or interrupts(after, was_in_list)
                or HEADING.match(text)
                or HR.match(after)
                or (table and not TABLE_DELIM.match(para[min(1, len(para) - 1)][1]))
                or DEFINITION.match(after)
                or after.startswith(OWN_HTML)
            ):
                flush()
            block: tuple[str, str, int] | None = None  # (tex, first prefix, next line)
            if m := re.fullmatch("\x00M(\\d+)\x00", line):
                block = (fences[int(m[1])][1], fences[int(m[1])][0], i + 1)
            elif stripped.startswith("$$") and not para:
                block = dollar_block(lines, i, prefix, stripped)
            elif AMS_OPEN.match(text) and (indent_of(line) < 4 or LIST.match(after)):
                block = ams_block(lines, i, prefix, text)
            if block:
                flush()
                tex, first, j = block
                cont = cont_of(first)
                out.extend(self.math_block(tex, first, cont))
                # exactly one &nbsp; spacer paragraph after every math block
                while j < len(lines) and (
                    blank(lines[j]) or strip_prefix(lines[j], cont).strip() == "&nbsp;"
                ):
                    j += 1
                out.extend([cont.rstrip(), cont + "&nbsp;", cont.rstrip()])
                i = j
                continue
            if not para and after.startswith(OWN_HTML):  # to the next blank line
                while i < len(lines) and not blank(lines[i]):
                    out.append(lines[i])
                    i += 1
                continue
            i += 1
            if blank(line):
                out.append(line)
            elif not para and (
                stripped == "<br>"  # this script's spacing round a divider
                or (DEFINITION.match(after) and not after.lstrip().startswith("[^"))
            ):  # a link reference definition: as it is, and no hard break after it
                out.append(line)
            elif not para and not text.strip():  # an empty list item
                out.append(line)
            elif HEADING.match(text) or (not para and HR.match(after)):
                out.append(prefix + self.inline(text))
            elif para and SETEXT.match(after):  # the underline of a heading
                out.extend(self.paragraph(para))
                out.append(line)
                para.clear()
            elif not para:
                depth = quotes(line)
                para.append((prefix, text))
            else:  # (markdown-it keeps a continuation line's indent in the text)
                q = quote(line)
                para.append((q, line[len(q) :]))
        flush()
        return out


def convert(
    s: str, links: dict[str, str], scrap_host: str | None
) -> tuple[str, list[str]]:
    """Return the gist Markdown for the scrap Markdown s, and the maths found."""
    lines, saved, fences = protect_code(
        s.replace("\r\n", "\n").replace("\x00", "\ufffd").split("\n")
    )
    s = "\n".join(lines)
    # scrap pages often pad a divider before a heading with &nbsp; paragraphs; the
    # <br> step below spaces those instead ("---" after a blank line: after text it
    # underlines a heading)
    s = re.sub(
        r"(?:(?<=\n\n)|\A)(?:&nbsp;\n\n)?---\n\n(?:&nbsp;\n\n)?(?=#{1,6}(?:[ \t]|$))",
        "---\n\n",
        s,
        flags=re.M,
    )
    c = Converter(links, scrap_host)
    s = "\n".join(c.blocks(s.split("\n"), fences))
    # breathing space round dividers before headings
    s = re.sub(
        r"(?<=\n)(?:\n<br>\n)?\n---\n\n(?:<br>\n\n)?(#)",
        r"\n<br>\n\n---\n\n<br>\n\n\1",
        s,
    )
    s = re.sub("\x00(\\d+)\x00", lambda m: saved[int(m[1])], s)
    return s.rstrip("\n") + "\n", c.maths


def check(md: str, page: str) -> int:
    """Compare the maths in md with what GitHub's markdown API (gfm mode) recognised
    in page, its HTML, and report maths left as raw text."""
    _, maths = convert(md, {}, "x")
    found = len(re.findall(r"<math-renderer", page))
    rest = re.sub(r"<math-renderer.*?</math-renderer>", "", page, flags=re.S)
    rest = re.sub(r"<pre.*?</pre>", "", rest, flags=re.S)
    # $`x`$ that GitHub did not take: a code span with a $ either side, or a stray
    # backtick that paired with one of its backticks
    raw = re.findall(r"\$<code[^>]*>.*?</code>\$|<code[^>]*>[^<]*\$</code>", rest)
    rest = re.sub(r"<code[^>]*>.*?</code>", "", rest, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "", rest))
    # and a $ next to a backtick, or a $...$ pair with TeX in it
    raw += re.findall(r"[^\n]{0,20}(?:`\$|\$`)[^\n]{0,20}", text)
    raw += re.findall(r"\$[^$\n]*[\\^_{}][^$\n]*\$", text)
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
