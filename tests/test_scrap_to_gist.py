"""skills/scrap-to-gist/scrap_to_gist.py: scrap Markdown to GitHub-gist Markdown.

The script is installed on its own (commands/install.sh), so it is loaded by path."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "skills" / "scrap-to-gist" / "scrap_to_gist.py"
_spec = importlib.util.spec_from_file_location("scrap_to_gist", SCRIPT)
assert _spec and _spec.loader
gist = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gist)

HOST = "https://scrap.example"
LINKS = {"paper": "https://gist.github.com/u/1"}


def convert(text: str) -> str:
    """The gist Markdown for text, checked to be unchanged by a second run."""
    once, _ = gist.convert(text, LINKS, HOST)
    twice, _ = gist.convert(once, LINKS, HOST)
    assert twice == once
    return once


PICTURE = '<p align="center"><picture>\n<img src="a.png">\n</picture></p>'
BLOCK = "```math\n\\Large\n{}\n```\n\n&nbsp;\n"


@pytest.mark.parametrize(
    "text, want",
    [
        # inline maths, and the GitHub form that survives a letter after the $
        ("the $n$th term", "the $`\\large n`$th term\n"),
        ("$\\Large x$ big", "$`\\large x`$ big\n"),
        # a line that is one \displaystyle formula stays left-aligned at \Large
        ("$\\displaystyle\\frac{a}{b}$", "$`\\displaystyle\\Large \\frac{a}{b}`$\n"),
        ("$\\displaystyle\\Large x$", "$`\\displaystyle\\Large x`$\n"),
        (
            "$\\displaystyle x$ then $y$",
            "$`\\large \\displaystyle x`$ then $`\\large y`$\n",
        ),
        # display maths: $$ lines, ```math fences, amsmath environments
        ("$$x$$", BLOCK.format("x")),
        ("$$\na+b\n$$", BLOCK.format("a+b")),
        ("```math\nx\n```\n&nbsp;\n\nnext", BLOCK.format("x") + "\nnext\n"),
        ("```math\n\\Large x\n```", BLOCK.format("x")),
        (
            "\\begin{align}\na &= b\n\\end{align}",
            BLOCK.format("\\begin{align}\na &= b\n\\end{align}"),
        ),
        ("> $$\n> a\n> $$", "> ```math\n> \\Large\n> a\n> ```\n>\n> &nbsp;\n>\n"),
        ("- $$\n  a\n  $$", "- $`\\displaystyle\\Large a`$\n"),
        # two formulas on one line are not one block
        (
            "$$a$$ and $$b$$",
            "$`\\displaystyle\\Large a`$ and $`\\displaystyle\\Large b`$\n",
        ),
        # money, escapes
        ("$5 and $10", "\\$5 and \\$10\n"),
        ("escaped \\$x\\$", "escaped \\$x\\$\n"),
        ("\\\\$x$", "\\\\$`\\large x`$\n"),
        # links: label, bare, table form, --link, never in code or maths
        ("[[page|A page]]", f"[A page]({HOST}/p/page)\n"),
        ("[[page]]", f"[page]({HOST}/p/page)\n"),
        (
            "| a | b |\n|---|---|\n| [[page\\|A]] | $a|b$ |",
            f"| a | b |\n|---|---|\n| [A]({HOST}/p/page) | \\$a|b\\$ |\n",
        ),
        ("see [[paper|it]]", "see [it](https://gist.github.com/u/1)\n"),
        ("$a * [[c]]$", "$`\\large a * [[c]]`$\n"),
        # code is never changed
        ("`$x$ [[page]]` and $y$", "`$x$ [[page]]` and $`\\large y`$\n"),
        ("```\n$x$ [[page]]\n$$y$$\n```", "```\n$x$ [[page]]\n$$y$$\n```\n"),
        ("~~~\n$x$\n---\n\n## H\n~~~", "~~~\n$x$\n---\n\n## H\n~~~\n"),
        ("para\n\n    $$x$$ [[page]] $5", "para\n\n    $$x$$ [[page]] $5\n"),
        # dividers: <br> before a heading, &nbsp; padding dropped; a setext heading kept
        (
            "a\n\n&nbsp;\n\n---\n\n&nbsp;\n\n## H",
            "a\n\n<br>\n\n---\n\n<br>\n\n## H\n",
        ),
        ("Title\n---\n\n## H", "Title\n---\n\n## H\n"),
        ("a\r\n\r\n$x$", "a\n\n$`\\large x`$\n"),
        # a quote or list item ends a paragraph, so its maths is a block of its own
        (
            "Answer:\n> $$\n> x^2\n> $$",
            "Answer:\n> ```math\n> \\Large\n> x^2\n> ```\n>\n> &nbsp;\n>\n",
        ),
        (
            "Intro:\n- $$\n  z\n  $$",
            "Intro:\n- $`\\displaystyle\\Large z`$\n",
        ),
        ("Costs $a\n- b$ c", "Costs \\$a\n- b\\$ c\n"),
        ("two\n2. not a list $x$", "two\\\n2. not a list $`\\large x`$\n"),
        # a lone backtick cannot pair with the backticks of $`...`$
        (
            "Use the ` key, then $y$ is fine.",
            "Use the \\` key, then $`\\large y`$ is fine.\n",
        ),
        ("``a`b $x$``", "``a`b $x$``\n"),
        # indented code in a list item, and 5 spaces after a marker, are code
        ("- a\n\n      code $q$\n\nb", "- a\n\n      code $q$\n\nb\n"),
        ("-     $x$ code", "-     $x$ code\n"),
        # a fence ends with its quote or list item
        ("> ```\n> $x$\n\n$y$", "> ```\n> $x$\n\n$`\\large y`$\n"),
        ("- ```\n  $x$\n$y$", "- ```\n  $x$\n$`\\large y`$\n"),
        # a $ in a URL, an autolink or a link destination stays as it is
        (
            "See https://example.com/api?$filter=x and $y$",
            "See https://example.com/api?$filter=x and $`\\large y`$\n",
        ),
        ("<https://e.com/$a> $5", "<https://e.com/$a> \\$5\n"),
        ("[x](https://e.com/$a) $5", "[x](https://e.com/$a) \\$5\n"),
        # spacing: &nbsp; kept round a divider with no heading after it; several
        # &nbsp; after a math block become one; ```math` is not a fence
        ("a\n\n&nbsp;\n\n---\n\n&nbsp;\n\nb", "a\n\n&nbsp;\n\n---\n\n&nbsp;\n\nb\n"),
        ("$$x$$\n\n&nbsp;\n\n&nbsp;\n\ntext", BLOCK.format("x") + "\ntext\n"),
        ("```math` $x$", "\\`\\`\\`math\\` $`\\large x`$\n"),
        # a newline in a paragraph is a hard break, as scrap shows it; not in code,
        # tables or maths, nor after a hard break already
        ("one $x$\ntwo\nthree", "one $`\\large x`$\\\ntwo\\\nthree\n"),
        ("> a\n> b", "> a\\\n> b\n"),
        ("- a\n  b", "- a\\\n  b\n"),
        ("a  \nb\\\nc", "a  \nb\\\nc\n"),
        ("$a\nb$", "$`\\large a\nb`$\n"),
        ("`a\nb`", "`a\nb`\n"),
        ("Title\nmore\n===", "Title\\\nmore\n===\n"),
        # sibling list items end the item before, whatever their number
        (
            "1. first $a$\n2. second $b$\n3. third",
            "1. first $`\\large a`$\n2. second $`\\large b`$\n3. third\n",
        ),
        (
            "1. Expand\n   the bracket\n2. Collect",
            "1. Expand\\\n   the bracket\n2. Collect\n",
        ),
        ("- a\n* b\n- c", "- a\n* b\n- c\n"),
        # a table ends the paragraph before it
        (
            "Results:\n| x | y |\n|---|---|\n| 1 | $x^2$ |",
            "Results:\n| x | y |\n|---|---|\n| 1 | $`\\large x^2`$ |\n",
        ),
        # definitions: no hard break, and not joined to the paragraph before
        (
            "[a]: https://example.com/a\n[b]: https://example.com/b\n\nSee [a].",
            "[a]: https://example.com/a\n[b]: https://example.com/b\n\nSee [a].\n",
        ),
        ("Text\n[^1]: One.\n[^2]: Two.", "Text\n[^1]: One.\n[^2]: Two.\n"),
        # HTML is text in scrap, so it is escaped; this script's own HTML is kept
        (
            "Use <slug> here, or <Enter>; a < b",
            "Use &lt;slug> here, or &lt;Enter>; a < b\n",
        ),
        ("<span>$x$</span>", "&lt;span>$`\\large x`$&lt;/span>\n"),
        (f"x\n{PICTURE}\n\n&nbsp;", f"x\n{PICTURE}\n\n&nbsp;\n"),
        # $$...$$ filling whole lines after a paragraph line is centred in scrap: a
        # math block, with no hard break before it
        (
            "Multiply out:\n$$\n(x+1)^2\n$$\nso $x=2$.",
            "Multiply out:\n" + BLOCK.format("(x+1)^2") + "\nso $`\\large x=2`$.\n",
        ),
        ("Text\n$$x$$\nmore", "Text\n" + BLOCK.format("x") + "\nmore\n"),
        # nested list items indented 4 or more end the item before; code in an item
        # stays code
        (
            "- Book the hall\n    - Tuesday or\n    - Thursday\n- Next",
            "- Book the hall\n    - Tuesday or\n    - Thursday\n- Next\n",
        ),
        (
            "2. Step\n    1. sub $x$\n    2. sub2",
            "2. Step\n    1. sub $`\\large x`$\n    2. sub2\n",
        ),
        ("- a\n    - b\n        - c\n- d", "- a\n    - b\n        - c\n- d\n"),
        ("- a\n\n      - code $x$", "- a\n\n      - code $x$\n"),
        # display maths in a list item stays in the item, left-aligned
        (
            "1. So $x = 2$.\n   $$x = 2,\\ 3$$\n2. Check",
            "1. So $`\\large x = 2`$.\\\n"
            "   $`\\displaystyle\\Large x = 2,\\ 3`$\n2. Check\n",
        ),
        ("- Then\n  ```math\n  y\n  ```", "- Then\\\n  $`\\displaystyle\\Large y`$\n"),
        (
            "- \\begin{align}\n  a &= b\n  \\end{align}",
            "- $`\\displaystyle\\Large \\begin{align} a &= b \\end{align}`$\n",
        ),
        # an email autolink is kept
        ("Mail <ann@example.com> or <b>", "Mail <ann@example.com> or &lt;b>\n"),
        ("Text\n    $$x$$", "Text\\\n    $`\\displaystyle\\Large x`$\n"),
        ("$$a\n$$b\n$$", "$`\\displaystyle\\Large a\n`$b\\\n\\$\\$\n"),
        ("Text\n$$a$$ b", "Text\\\n$`\\displaystyle\\Large a`$ b\n"),
        (
            "> Text\n> $$\n> y\n> $$",
            "> Text\n> ```math\n> \\Large\n> y\n> ```\n>\n> &nbsp;\n>\n",
        ),
    ],
)
def test_convert(text, want):
    assert convert(text) == want


CASES = json.loads((Path(__file__).parent / "maths_cases.json").read_text())["cases"]


@pytest.mark.parametrize("text, want", CASES)
def test_scrap_maths_cases(text, want):
    """What scrap reads as maths is converted, and what it reads as text stays text."""
    out = convert(text)
    _, found = gist.convert(text, LINKS, HOST)
    assert [t.strip() for t in found] == [t.strip() for _, t in want]
    if not want:
        assert "$`\\" not in out and "```math" not in out


def test_a_link_needs_the_scrap_address():
    with pytest.raises(SystemExit, match="SCRAP_URL"):
        gist.convert("[[page]]", {}, None)
    assert gist.convert("no links", {}, None)[0] == "no links\n"


def run(cwd: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={"PATH": "/usr/bin:/bin"} | env,
    )


def test_cli(tmp_path):
    (tmp_path / "in.md").write_text("[[page]] $\\cancel{x}$\n")
    done = run(tmp_path, "in.md", "out.md", "--title", "T", SCRAP_URL=f"{HOST}/mcp")
    assert done.returncode == 0, done.stderr
    out = (tmp_path / "out.md").read_text()
    assert out == f"# T\n\n[page]({HOST}/p/page) $`\\large \\cancel{{x}}`$\n"
    assert "\\cancel" in done.stderr


def test_check(tmp_path):
    md = tmp_path / "gist.md"
    md.write_text("a $`\\large x`$ b\n\n```math\n\\Large\ny\n```\n")
    good = tmp_path / "good.html"
    # As GitHub's markdown API (gfm mode) writes them
    inline = (
        '<math-renderer class="js-inline-math" style="display: inline-block" '
        'data-run-id="1">$\\large x$</math-renderer>'
    )
    block = (
        '<math-renderer class="js-display-math" style="display: block" '
        'data-run-id="1">$$\\Large\ny\n$$</math-renderer>'
    )
    good.write_text(f"<p>a {inline} b</p>\n{block}\n")
    ok = run(tmp_path, "--check", "gist.md", "good.html")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = {
        # $`x`$ not taken as maths
        "code": '<p>a $<code class="notranslate">\\large x</code>$ b</p>',
        # a stray backtick paired with one of $`x`$'s
        "paired": '<p>the <code class="notranslate"> key, $</code>\\large x`$ ok</p>',
        # plain $...$ left as text
        "plain": "<p>a $x^2$th b</p>",
    }
    for name, html in bad.items():
        (tmp_path / f"{name}.html").write_text(f"{html}\n{block}\n")
        failed = run(tmp_path, "--check", "gist.md", f"{name}.html")
        assert failed.returncode == 1, name
        assert "raw maths" in failed.stdout, name
    # what is missing is named; a footnote's maths and a ```math block left as code
    # are said to be so
    notes = (
        '<p>A <math-renderer class="js-inline-math">$\\large y$</math-renderer></p>\n'
        '<section data-footnotes="" class="footnotes"><ol><li><p>area '
        '$<code class="notranslate">\\large x^2</code>$.</p></li></ol></section>'
        '<pre lang="math" class="notranslate"><code class="notranslate">\\Large\nz\n'
        "</code></pre>\n"
    )
    (tmp_path / "notes.md").write_text(
        "A $`\\large y`$\n\n[^1]: area $`\\large x^2`$.\n\n```math\n\\Large\nz\n```\n"
    )
    (tmp_path / "notes.html").write_text(notes)
    failed = run(tmp_path, "--check", "notes.md", "notes.html")
    assert failed.returncode == 1
    assert "not recognised: x^2 (inside a footnote" in failed.stdout
    assert "not recognised: z\n" in failed.stdout
    assert "math block shown as code: z" in failed.stdout
    # a path with backslashes in the text is not maths
    (tmp_path / "path.html").write_text(
        f"<p>a {inline} b C:\\Users\\me $5</p>\n{block}\n"
    )
    assert run(tmp_path, "--check", "gist.md", "path.html").returncode == 0
