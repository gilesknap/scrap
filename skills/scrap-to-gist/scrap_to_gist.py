#!/usr/bin/env python3
"""Convert a scrap page's Markdown body into GitHub-gist Markdown that looks like scrap.

Usage: scrap_to_gist.py IN.md OUT.md [--title "H1 title"] [--scrap-host URL]
                        [--link slug=https://...]...

Transforms (all idempotent, so re-running on its own output is safe):
  * [[slug|label]] / [[slug]] -> [label](URL): --link slug=URL wins, else the scrap
    page URL (--scrap-host, default $SCRAP_URL; needed only when a link uses it)
  * standalone "$$...$$" lines -> ```math blocks (centred, as in scrap)
  * standalone "$\\displaystyle ...$" lines -> $`\\displaystyle\\Large ...`$
    (left-aligned, as in scrap)
  * every ```math block starts with \\Large and is followed by an &nbsp; line
  * inline $...$ (outside code blocks) -> $`\\large ...`$
  * <br> above and below each "---" divider that precedes a heading
  * optional "# title" prepended (scrap keeps the title outside the body)
Lines using \\cancel are reported on stderr: GitHub does not render it, so swap in
an image (see SKILL.md).

Only the standard library is used.
"""

import argparse
import os
import re
import sys

LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def convert(s: str, links: dict[str, str], scrap_host: str | None) -> str:
    """Return the gist Markdown for the scrap Markdown `s`."""
    # scrap pages often pad dividers with &nbsp; paragraphs; the divider step
    # re-adds spacing
    s = re.sub(r"(?:&nbsp;\n\n)?^---\n\n(?:&nbsp;\n\n)?", "---\n\n", s, flags=re.M)

    def link(m: re.Match[str]) -> str:
        slug, label = m.group(1), m.group(2) or m.group(1)
        if slug in links:
            return f"[{label}]({links[slug]})"
        if not scrap_host:
            sys.exit(
                f"[[{slug}]] needs the scrap address: pass --scrap-host or set "
                f"SCRAP_URL (or --link {slug}=URL)"
            )
        return f"[{label}]({scrap_host}/p/{slug})"

    s = LINK.sub(link, s)

    # standalone display maths lines -> fenced math blocks
    s = re.sub(r"^\$\$(.+?)\$\$[ \t]*$", r"```math\n\1\n```", s, flags=re.M)
    # a standalone $\displaystyle ...$ line is LEFT-aligned in scrap, but a ```math
    # block is centred on GitHub; keep it inline (own paragraph) so the alignment
    # matches scrap
    s = re.sub(
        r"^\$\\displaystyle\\?(?:large|Large)?\s*(.+?)\$[ \t]*$",
        r"$`\\displaystyle\\Large \1`$",
        s,
        flags=re.M,
    )

    # \Large at the top of every math block
    s = re.sub(r"```math\n(?:\\(?:large|Large)\n)?", "```math\n\\\\Large\n", s)

    # exactly one &nbsp; spacer paragraph after every math block
    s = re.sub(
        r"(```math\n(?:(?!```).)*?\n```)[ \t]*\n(?:\s*&nbsp;[ \t]*\n)?\s*",
        r"\1\n\n&nbsp;\n\n",
        s,
        flags=re.S,
    )

    # inline maths -> $`\large ...`$ : the backtick form survives a letter straight
    # after the closing $ ("$n$th", "$x$s"), which makes GitHub show plain $...$ as
    # raw text
    parts = re.split(r"(```.*?```)", s, flags=re.S)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(
            r"(?<![\$\\`])\$(?![\$`])([^\$\n]+?)\$",
            lambda m: (
                "$`\\large " + re.sub(r"^\\(?:large|Large)\s*", "", m.group(1)) + "`$"
            ),
            parts[i],
        )
    s = "".join(parts)

    # breathing space round dividers before headings
    return re.sub(
        r"(?:\n<br>\n)?\n---\n\n(?:<br>\n\n)?(#)", r"\n<br>\n\n---\n\n<br>\n\n\1", s
    )


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
    a = p.parse_args()

    links = dict(x.split("=", 1) for x in a.link)
    host = a.scrap_host.rstrip("/").removesuffix("/mcp") if a.scrap_host else None
    with open(a.inp, encoding="utf-8") as f:
        s = convert(f.read(), links, host)
    if a.title and not s.lstrip().startswith("# "):
        s = f"# {a.title}\n\n{s.lstrip()}"
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(s)
    for n, line in enumerate(s.splitlines(), 1):
        if "\\cancel" in line:
            print(
                f"warning: line {n} uses \\cancel (GitHub does not render it)",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
