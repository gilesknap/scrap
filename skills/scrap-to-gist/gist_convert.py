"""scrap Markdown to GitHub-gist Markdown: the conversion scrap_to_gist.py runs (its
docstring says what it does), and blob_refs, the references to scrap's own files a
body holds (for gist_images.py). Only the standard library is used."""

import os
import re
import sys

# scrap_markdown.py is beside this module (also when it is loaded by path)
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
    OWN_BLOB,
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
    list_match,
    math_at,
    protect_code,
    quote,
    quotes,
    split_at,
    strip_prefix,
    track_list,
)

# --- inline -------------------------------------------------------------------------


def _size_off(tex: str) -> str:
    """A math block's TeX: no \\large or \\Large first, no blank lines round it."""
    tex = re.sub(r"^[ \t]*\\(?:large|Large)(?![A-Za-z])[ \t]*", "", tex.strip("\n"))
    return tex.strip("\n")


class Converter:
    def __init__(
        self,
        links: dict[str, str],
        scrap_host: str | None,
        images: dict[str, str] | None = None,
        raw_base: str | None = None,
    ):
        self.links = links
        self.host = scrap_host
        self.maths: list[str] = []
        self.spans: list[tuple[int, int]] = []  # where inline() found maths in its src
        self.images = images or {}  # a reference to a scrap file -> its gist file
        self.by_sha = {}  # the same, by the file's sha (another form of reference)
        for ref, name in self.images.items():
            if m := OWN_BLOB.match(ref):
                self.by_sha.setdefault(m[1], name)
        self.raw_base = raw_base.rstrip("/") if raw_base else None
        self.refs: list[str] = []  # every reference to a scrap file, outside code
        self.unmapped: list[str] = []  # those left as they are

    def blob(self, ref: str) -> str:
        """A reference to one of scrap's files (OWN_BLOB): the raw URL of its gist
        file if --images maps it (by the reference, else by its sha), else as it is."""
        self.refs.append(ref)
        name = self.images.get(ref) or self.by_sha.get(ref[len("/api/blobs/") :][:64])
        if not name or not self.raw_base:
            self.unmapped.append(ref)
            return ref
        return f"{self.raw_base}/{name}"

    def dest(self, s: str, start: int) -> str:
        """s with the link destination at start swapped by blob(), if it is a
        reference to one of scrap's files."""
        start += s[start : start + 1] == "<"
        m = OWN_BLOB.match(s, start)
        return s[:start] + self.blob(m[0]) + s[m.end() :] if m else s

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
                out.append(self.dest(m[0], 2))
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
                self.spans.append((i, end))
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
        tex = _size_off(tex)
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

    def fills_lines(
        self, para: list[tuple[str, str]], lines: list[str], i: int, j: int, prefix: str
    ) -> bool:
        """Whether lines i to j (a $$ block after a paragraph line, so inline maths in
        scrap) are one $$...$$ and nothing else. scrap draws that centred, as display
        maths, so it becomes a math block too."""
        cont = cont_of(prefix)
        seg = [lines[i][len(prefix) :]] + [
            strip_prefix(x, cont) for x in lines[i + 1 : j]
        ]
        if indent_of(lines[i]) >= 4:
            return False  # indented, it continues the paragraph
        if any(x.startswith("\x00") for x in lines[i:j]):
            return False  # a fence in it would end the paragraph in scrap
        before = "\n".join(t for _, t in para) + "\n"
        joined = before + "\n".join(seg).rstrip()
        # read as scrap reads the paragraph: one formula from the $$ to the end
        probe = Converter({}, "x")
        probe.inline(joined)
        start = len(before) + len(seg[0]) - len(seg[0].lstrip())
        return (start, len(joined)) in probe.spans

    def blocks(self, lines: list[str], fences: list[tuple[str, str]]) -> list[str]:
        out: list[str] = []
        para: list[tuple[str, str]] = []  # a paragraph's lines: (prefix, text)
        depth = 0  # the paragraph's quote depth
        list_w = 0  # the content column of the list item we are in (0: none)

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
            after = line[len(quote(line)) :]
            fence = re.fullmatch("\x00M(\\d+)\x00", line)
            # (a math fence's placeholder stands for its first line)
            ctx = fences[int(fence[1])][0] + "```" if fence else line
            was_list_w, lm = list_w, None
            if not blank(line):
                list_w, lm = track_list(ctx, list_w, bool(para))
            prefix, text = split_at(line, lm)
            stripped = text.strip()
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            table = "|" in text and TABLE_DELIM.match(nxt[len(quote(nxt)) :])
            # what ends a paragraph: a blank line, a new quote, a list item that is not
            # empty (outside a list an ordered one only from 1), a heading, a thematic
            # break, a table, a definition
            if para and (
                blank(line)
                or quotes(line) > depth
                or interrupts(ctx[len(quote(ctx)) :], was_list_w)
                or HEADING.match(text)
                or HR.match(after)
                or (table and not TABLE_DELIM.match(para[min(1, len(para) - 1)][1]))
                or DEFINITION.match(after)
                or after.startswith(OWN_HTML)
            ):
                flush()
            block: tuple[str, str, int] | None = None  # (tex, first prefix, next line)
            if fence:
                block = (fences[int(fence[1])][1], fences[int(fence[1])][0], i + 1)
            elif stripped.startswith("$$"):
                block = dollar_block(lines, i, prefix, stripped)
                if (
                    block
                    and para
                    and not self.fills_lines(para, lines, i, block[2], prefix)
                ):
                    block = None
            elif AMS_OPEN.match(text) and (indent_of(line) < 4 or LIST.match(after)):
                block = ams_block(lines, i, prefix, text)
            words = " ".join(_size_off(block[0]).split()) if block else ""
            if block and list_w and words and not re.search(r"[$`]", words):
                # GitHub leaves a ```math block in a list that has inline maths as
                # code: keep it in the item, as display-style maths on its own line
                tex, first, i = block
                q = quote(first)
                rest = first[len(q) :]
                if list_match(rest, was_list_w):
                    flush()
                if para:
                    para.append((q, rest + f"$${words}$$"))
                else:
                    depth = quotes(first)
                    para.append((first, f"$${words}$$"))
                continue
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
                d = DEFINITION.match(after)
                if d:
                    at = len(line) - len(after) + d.end()
                    at += len(line[at:]) - len(line[at:].lstrip(" \t"))
                    line = self.dest(line, at)
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
    s: str,
    links: dict[str, str],
    scrap_host: str | None,
    images: dict[str, str] | None = None,
    raw_base: str | None = None,
) -> tuple[str, list[str]]:
    """Return the gist Markdown for the scrap Markdown s, and the maths found. images
    maps a reference to a scrap file to the name of its gist file, at raw_base."""
    s, c = converted(s, links, scrap_host, images, raw_base)
    return s, c.maths


def blob_refs(s: str) -> list[str]:
    """The references to scrap's own files in the scrap Markdown s, outside code, in
    order (repeats kept), as the conversion finds them."""
    return converted(s, {}, "x")[1].refs


def converted(
    s: str,
    links: dict[str, str],
    scrap_host: str | None,
    images: dict[str, str] | None = None,
    raw_base: str | None = None,
) -> tuple[str, Converter]:
    """convert(), returning the Converter (its maths and file references) too."""
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
    c = Converter(links, scrap_host, images, raw_base)
    s = "\n".join(c.blocks(s.split("\n"), fences))
    # breathing space round dividers before headings
    s = re.sub(
        r"(?<=\n)(?:\n<br>\n)?\n---\n\n(?:<br>\n\n)?(#)",
        r"\n<br>\n\n---\n\n<br>\n\n\1",
        s,
    )
    s = re.sub("\x00(\\d+)\x00", lambda m: saved[int(m[1])], s)
    return s.rstrip("\n") + "\n", c
