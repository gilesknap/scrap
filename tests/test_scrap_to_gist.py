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
        ("- $$\n  a\n  $$", "- ```math\n  \\Large\n  a\n  ```\n\n  &nbsp;\n"),
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
    good.write_text(
        '<p>a <math-renderer class="js-inline-math">$x$</math-renderer> b</p>'
        '<math-renderer class="js-display-math">$$y$$</math-renderer>'
    )
    bad = tmp_path / "bad.html"
    bad.write_text(
        "<p>a $<code>\\large x</code>$ b</p>"
        '<math-renderer class="js-display-math">$$y$$</math-renderer>'
    )
    ok = run(tmp_path, "--check", "gist.md", "good.html")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    failed = run(tmp_path, "--check", "gist.md", "bad.html")
    assert failed.returncode == 1
    assert "raw maths" in failed.stdout
