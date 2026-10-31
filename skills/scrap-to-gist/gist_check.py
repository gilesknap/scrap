"""scrap_to_gist.py --check: compare the maths in gist Markdown with what GitHub's
markdown API (gfm mode) recognised in its HTML, and name what GitHub would show as raw
text, and any link to a scrap file left. Only the standard library is used."""

import html
import os
import re
import sys
from collections import Counter

# gist_convert.py is beside this module (also when it is loaded by path)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gist_convert import converted  # noqa: E402


def _plain(tex: str) -> str:
    """TeX as --check compares it: no $ or size commands, spaces collapsed."""
    for _ in range(3):  # GitHub escapes < in maths twice (&amp;lt;)
        tex = html.unescape(tex)
    tex = tex.strip().strip("$").strip().strip("`").strip()
    tex = re.sub(r"^(?:\\(?:displaystyle|large|Large)(?![A-Za-z])\s*)+", "", tex)
    tex = re.sub(r"\\{3,}", r"\\\\", tex)  # GitHub writes a TeX \\ as \\\
    return " ".join(tex.split())


def _text(part: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", part)).split())


FOOTNOTE = (
    " (inside a footnote: GitHub does not draw maths there; move it into the body "
    "or write it in words)"
)


def check(md: str, page: str) -> int:
    """Compare the maths in md with what GitHub's markdown API (gfm mode) recognised
    in page, its HTML, and name the maths it left as raw text."""
    _, c = converted(md, {}, "x")
    maths = c.maths
    drawn = re.findall(r"<math-renderer[^>]*>(.*?)</math-renderer>", page, flags=re.S)
    print(f"{len(drawn)} maths recognised by GitHub, {len(maths)} in the markdown")
    section = page.partition("<section data-footnotes")[2].partition("</section>")[0]
    in_notes = {
        _plain(x) for x in re.findall(r"\$<code[^>]*>(.*?)</code>\$", section, re.S)
    }

    def where(tex: str) -> str:
        return FOOTNOTE if tex in in_notes else ""

    missing = Counter(_plain(t) for t in maths) - Counter(_plain(t) for t in drawn)
    for tex in missing.elements():
        print(f"not recognised: {tex}{where(tex)}")
    # a ```math block GitHub left as code (it does so in a list with inline maths)
    for tex in re.findall(
        r'<pre lang="math"[^>]*><code[^>]*>(.*?)</code></pre>', page, re.S
    ):
        print(f"math block shown as code: {_plain(tex)}")
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
    for r in raw:
        r = _text(r)
        print(f"raw maths: {r}{where(_plain(r))}")
    for ref in c.refs:  # GitHub cannot reach scrap's files
        print(f"scrap file link left: {ref} (copy it into the gist: see SKILL.md)")
    return 1 if missing or raw or c.refs else 0
