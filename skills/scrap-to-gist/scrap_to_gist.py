#!/usr/bin/env python3
"""Convert a scrap page's Markdown body into GitHub-gist Markdown that looks like scrap.

Usage: scrap_to_gist.py IN.md OUT.md [--title "H1 title"] [--scrap-host URL]
                        [--link slug=https://...]...
                        [--images MAP.json --gist-raw-base RAW_URL]
       scrap_to_gist.py --check GIST.md API.html

Maths is found with scrap's own rules (scrap_markdown.py beside this script, ported
from src/scrap/maths.py and web/src/mathrules.ts, the cases in tests/maths_cases.json):
$...$ and $$...$$ in a line, $$ ... $$ on lines of their own, a top-level amsmath
environment, and ```math fences. Code (inline code spans, ``` and ~~~ fences, indented
code) is never changed.
Known limit: as in scrap, money followed by a code span holding a $ ("$5 and `$x`")
reads as maths up to that $.
Deliberate differences: a line such as "$$a$$ and $$b$$" is two formulas here, where
scrap reads one block "a$$ and $$b" (which KaTeX cannot draw); and a $ in a bare URL
(https://..., www....) never starts maths, so the link survives.

Transforms (all idempotent, so re-running on its own output is safe):
  * [[slug|label]] / [[slug]] (and [[slug\\|label]] in a table) -> [label](URL):
    --link slug=URL wins, else the scrap page URL (--scrap-host, default $SCRAP_URL;
    needed only when a link uses it)
  * display maths ($$ blocks, amsmath environments, ```math fences; centred in scrap)
    -> a ```math block that starts \\Large, followed by an &nbsp; paragraph
  * display maths in a list item -> $`\\displaystyle\\Large ...`$ on its own line
    (GitHub shows a ```math block as code in a list that has inline maths)
  * a line that is only "$\\displaystyle ...$" -> $`\\displaystyle\\Large ...`$
    (left-aligned, as in scrap)
  * other inline $...$ -> $`\\large ...`$, and $$...$$ within a line ->
    $`\\displaystyle\\Large ...`$
  * a $ that scrap does not read as maths ("$5 and $10") -> \\$, so GitHub leaves it
    (not in a URL); a lone backtick -> \\`, so it cannot pair with $`...`$
  * a line break inside a paragraph -> a hard break (a trailing \\), as scrap shows
    it (it renders with breaks: true; a gist does not)
  * <br> above and below each "---" divider that precedes a heading
  * a link or image to one of scrap's files (/api/blobs/<sha>, .../preview?size=N,
    ...?download=1; also in a link reference definition) -> the raw URL of its gist
    file, RAW_URL/<name>, with --images (the mapping gist_images.py writes: the
    reference as the body has it, or another of the same sha, -> name); one not
    mapped is left as it is, with a warning on stderr
  * optional "# title" prepended (scrap keeps the title outside the body)
Maths using \\cancel is reported on stderr: GitHub does not draw it, so swap in an
image (see SKILL.md).

--check reads the HTML of GitHub's markdown API (in gfm mode: markdown mode does not
mark maths) for GIST.md and reports maths GitHub did not recognise (it would show as
raw text), and any link to a scrap file left (GitHub cannot reach it). Only the
standard library is used.
"""

import argparse
import json
import os
import re
import sys

# the modules are beside this script (also when it is loaded by path)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gist_check import check  # noqa: E402
from gist_convert import Converter, blob_refs, convert, converted  # noqa: E402

# Where a gist's files are served (the id is hex; the user a GitHub login)
RAW_BASE = re.compile(
    r"https://gist\.githubusercontent\.com/[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
    r"/[0-9a-f]+/raw/?"
)

__all__ = ["Converter", "blob_refs", "check", "convert", "converted", "main"]


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
        "--images",
        metavar="MAP.json",
        help="the mapping gist_images.py wrote: each reference to a scrap image, as "
        "the body has it, to its gist file's name",
    )
    p.add_argument(
        "--gist-raw-base",
        metavar="URL",
        help="https://gist.githubusercontent.com/<user>/<id>/raw, where --images' "
        "files are",
    )
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
    images = None
    if a.images:
        if not a.gist_raw_base:
            sys.exit("--images needs --gist-raw-base")
        if not RAW_BASE.fullmatch(a.gist_raw_base):
            sys.exit(
                f"--gist-raw-base must be https://gist.githubusercontent.com/<user>/"
                f"<gist id>/raw, with the user and id written out: not "
                f"{a.gist_raw_base!r}"
            )
        with open(a.images, encoding="utf-8") as f:
            images = json.load(f)
    s, c = converted(src, links, host, images, a.gist_raw_base)
    maths = c.maths
    if a.title and not s.lstrip().startswith("# "):
        s = f"# {a.title}\n\n{s.lstrip()}"
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(s)
    for ref in dict.fromkeys(c.unmapped):
        print(
            f"warning: scrap file not copied, left as it is (it does not resolve on "
            f"GitHub): {ref}",
            file=sys.stderr,
        )
    for tex in maths:
        if "\\cancel" in tex:
            first = tex.strip().split("\n")[0][:60]
            print(
                f"warning: maths uses \\cancel (GitHub does not draw it): {first}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
