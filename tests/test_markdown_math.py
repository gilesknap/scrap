"""maths.py, through markdown.py: maths found as the PWA finds it (mathrules.ts), held
to the cases web/tests/math.test.ts holds the PWA to (maths_cases.json)."""

import json
from pathlib import Path

import pytest

from scrap.markdown import Link, parser, plain, rewrite, wiki_targets

CASES = json.loads((Path(__file__).parent / "maths_cases.json").read_text())["cases"]
KIND = {
    "math_inline": "inline",
    "math_inline_double": "double",
    "math_block": "block",
    "amsmath": "block",
}


def maths(text: str) -> list[list[str]]:
    """Each maths token in text: [kind, its TeX], as maths_cases.json has them."""
    out = []
    for t in parser().parse(text):
        for c in [t, *(t.children or [])]:
            if c.type in KIND:
                out.append([KIND[c.type], c.content.strip()])
    return out


@pytest.mark.parametrize(("text", "found"), CASES)
def test_maths_is_found_as_the_pwa_finds_it(text: str, found: list[list[str]]):
    assert maths(text) == found


def test_money_is_searched_as_typed():
    assert plain("It cost $5 and $10") == "It cost $5 and $10"


def test_markup_in_a_formula_is_tex_not_emphasis_or_a_link():
    inline = "Then $a_1 * b_2 * [[c]]$ and [[real]]"
    assert wiki_targets(inline) == ["real"]
    assert plain(inline) == "Then a_1 * b_2 * [[c]] and real"
    block = "$$\n_x_ [[page]] *y*\n$$\n\n\\begin{gather}\n[[other]]_1\n\\end{gather}"
    assert wiki_targets(block) == []
    assert "_x_ [[page]] *y*" in plain(block)


def test_links_in_a_formula_are_not_rewritten():
    def show(link: Link) -> str:
        return f"<{link.target}>"

    text = "$[[a]]$ [[b]]\n\n$$\n[[c]] [d](/p/d)\n$$"
    assert rewrite(text, show) == "$[[a]]$ <b>\n\n$$\n[[c]] [d](/p/d)\n$$"
