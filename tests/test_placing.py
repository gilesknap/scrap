# ruff: noqa: E501
"""Where add_svg's and the upload's after puts an embed (#480): right after the
line the passage ends on, inside its list item or quote (a tight list kept tight
with a hard break); after a block that cannot be split. The page's blocks, its
lists' tightness and its rendered text stay as they were (checked by parsing it)."""

import re

import pytest

from scrap.markdown import parser
from scrap.store import InvalidError
from scrap.store.placing import placed_after

E = "![d](e)"
MD = parser()
CONTAINERS = ("list_item_open", "blockquote_open")


def blocks(text):
    """The text's blocks, paragraphs left out (a split adds one, as the embed is)."""
    keep = ("paragraph_open", "paragraph_close", "inline")
    return [(t.type, t.level) for t in MD.parse(text) if t.type not in keep]


def tights(text):
    """Each list's tightness, as rendered (no <p> in its items)."""
    out, stack = [], []
    for t in MD.parse(text):
        if t.type in ("bullet_list_open", "ordered_list_open"):
            stack.append(len(out))
            out.append(True)
        elif t.type in ("bullet_list_close", "ordered_list_close"):
            stack.pop()
        elif t.type == "paragraph_open" and stack and not t.hidden:
            out[stack[-1]] = False
    return out


def seen(text):
    """The rendered text, the embed's image left out."""
    html = MD.render(text).replace('<img src="e" alt="d" />', " ")
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def holder(text):
    """The list items and quotes the embed is in."""
    stack = []
    for t in MD.parse(text):
        if t.type in CONTAINERS:
            stack.append(t.type)
        elif t.type in ("list_item_close", "blockquote_close"):
            stack.pop()
        elif t.type == "inline" and E in t.content:
            return stack
    raise AssertionError("no embed")


EXAM_LINES = "Q3 A ladder leans on a wall.\n(a) Find the height.\nAnswer: 4 m\n(b) Find the angle.\nAnswer: 30°\n\nQ4"
EXAM_LIST = (
    "Q3\n\n1. Show that x = 2.\n   Answer: shown\n2. Find y.\n   Answer: 5\n\nQ4"
)
LI, BQ = "list_item_open", "blockquote_open"
# fmt: off
CASES = [
    # a paragraph is split after the line (the exam layout of (a)/(b) lines)
    ("para", "Q1 find x\nWorking:\n\nQ2", "find x", f"Q1 find x\n\n{E}\n\nWorking:\n\nQ2", []),
    ("exam lines", EXAM_LINES, "(a) Find the height.",
     f"Q3 A ladder leans on a wall.\n(a) Find the height.\n\n{E}\n\nAnswer: 4 m\n(b) Find the angle.\nAnswer: 30°\n\nQ4", []),
    ("end", "Q1 find x", "find x", f"Q1 find x\n\n{E}", []),
    ("end newline", "Q1 find x\n", "find x\n", f"Q1 find x\n\n{E}", []),
    # a tight list stays tight: a hard break, the embed on the next line at the
    # item's indent, broken from what follows
    ("exam list", EXAM_LIST, "Show that x = 2.",
     f"Q3\n\n1. Show that x = 2.\\\n   {E}\\\n   Answer: shown\n2. Find y.\n   Answer: 5\n\nQ4", [LI]),
    ("exam list, last line", EXAM_LIST, "Answer: shown",
     f"Q3\n\n1. Show that x = 2.\n   Answer: shown\\\n   {E}\n2. Find y.\n   Answer: 5\n\nQ4", [LI]),
    ("nested", "- a\n  - b\n    more b\n  - c\n- d", "- b", f"- a\n  - b\\\n    {E}\\\n    more b\n  - c\n- d", [LI, LI]),
    ("lazy line", "1. a\nlazy\n2. b", "1. a", f"1. a\\\n   {E}\\\n   lazy\n2. b", [LI]),
    ("ATX in a list", "- a\n  # h\n  b\n\nend", "# h", f"- a\n  # h\n  {E}\n  b\n\nend", [LI]),
    ("parent before its sublist", "- a1\n  - b1\n- c1", "a1", f"- a1\\\n  {E}\n  - b1\n- c1", [LI]),
    ("fence in a tight item", "1. a\n   ```\n   code\n   ```\n2. b", "code", f"1. a\n   ```\n   code\n   ```\n   {E}\n2. b", [LI]),
    # tabs count to the next stop of 4, and the embed is indented with spaces
    ("obsidian tabs", "- a1\n\t- b1\n\t\t- c1\n\t\t- c2\n\t- b2\n- a2", "c1",
     f"- a1\n\t- b1\n\t\t- c1\\\n          {E}\n\t\t- c2\n\t- b2\n- a2", [LI, LI, LI]),
    ("tab after the marker", "-\ta\n\tmore\n-\tb", "a", f"-\ta\\\n    {E}\\\n\tmore\n-\tb", [LI]),
    ("tabbed nesting", "- a\n\t- bb\n\t  more\n- c", "bb", f"- a\n\t- bb\\\n      {E}\\\n\t  more\n- c", [LI, LI]),
    # a loose list keeps paragraphs
    ("loose list", "- a\n\n- b\n\n- c", "b", f"- a\n\n- b\n\n  {E}\n\n- c", [LI]),
    ("loose second paragraph", "1. q\n\n   second\n   line2\n\n2. r", "second",
     f"1. q\n\n   second\n\n   {E}\n\n   line2\n\n2. r", [LI]),
    ("table in a list", "- item\n\n  | a | b |\n  |---|---|\n  | 1 | 2 |\n\n- item2", "| 1 | 2 |",
     f"- item\n\n  | a | b |\n  |---|---|\n  | 1 | 2 |\n\n  {E}\n\n- item2", [LI]),
    # a quote keeps it, quoted; two quotes stay two
    ("quote", "> q1\n> q2\n\nend", "q1", f"> q1\n>\n> {E}\n>\n> q2\n\nend", [BQ]),
    ("lazy quote", "> q1\nlazy\n\nend", "q1", f"> q1\n>\n> {E}\n>\n> lazy\n\nend", [BQ]),
    ("two quotes", "> q1\n\n> q2", "q1", f"> q1\n>\n> {E}\n\n> q2", [BQ]),
    ("nested quote, lazy outer line", "> > deep1\n> > deeper2\n> outer3", "deep1",
     f"> > deep1\n> >\n> > {E}\n> >\n> > deeper2\n> outer3", [BQ, BQ]),
    # blocks that cannot be split: after their end
    ("fence", "```\nx = 1\n\ny = 2\n```\nafter", "x = 1", f"```\nx = 1\n\ny = 2\n```\n\n{E}\n\nafter", []),
    ("math fence", "Q\n\n```math\na\n\nb\n```\nend", "```math\na", f"Q\n\n```math\na\n\nb\n```\n\n{E}\n\nend", []),
    ("indented code", "para\n\n    code1\n\n    code2\n\nend", "code1", f"para\n\n    code1\n\n    code2\n\n{E}\n\nend", []),
    ("table", "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\nnext", "| 1 | 2 |",
     f"| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n{E}\n\nnext", []),
    ("display maths", "Q\n\n$$\na=1\n\nb=2\n$$\n\nend", "a=1", f"Q\n\n$$\na=1\n\nb=2\n$$\n\n{E}\n\nend", []),
    ("amsmath", "Q\n\n\\begin{align}\na\n\nb\n\\end{align}\n\nend", "a\n\nb",
     f"Q\n\n\\begin{{align}}\na\n\nb\n\\end{{align}}\n\n{E}\n\nend", []),
    ("setext", "Title\n=====\nbody", "Title", f"Title\n=====\n\n{E}\n\nbody", []),
    ("ATX", "# Q1\nFind x", "Q1", f"# Q1\n\n{E}\n\nFind x", []),
    # a split that would change the page: after the paragraph instead
    ("no new list", "Q1 x\n2. y\n\nend", "Q1", f"Q1 x\n2. y\n\n{E}\n\nend", []),
    ("inline code", "a `x\ny` b\n\nc", "a `x", f"a `x\ny` b\n\n{E}\n\nc", []),
    ("link across lines", "see [the\nlink](u) ok\nnext\n\nend", "see [the", f"see [the\nlink](u) ok\nnext\n\n{E}\n\nend", []),
    ("bold across lines", "**bold\ntext** end\nnext\n\nend", "**bold", f"**bold\ntext** end\nnext\n\n{E}\n\nend", []),
]
# fmt: on


@pytest.mark.parametrize(
    "name, body, after, placed, inside", CASES, ids=[c[0] for c in CASES]
)
def test_the_embed_goes_after_the_line_and_the_page_keeps_its_shape(
    name, body, after, placed, inside
):
    out = placed_after(body, after, [E])
    assert out == placed
    assert blocks(out) == blocks(body)
    assert tights(out) == tights(body)
    assert seen(out) == seen(body)
    assert holder(out) == inside


def test_several_embeds_go_together():
    f = E.replace("d", "f")
    out = placed_after("- a\n- b", "a", [E, f])
    assert out == f"- a\\\n  {E}\\\n  {f}\n- b"
    assert blocks(out) == blocks("- a\n- b") and tights(out) == [True]
    assert placed_after("p1\np2", "p1", [E, f]) == f"p1\n\n{E}\n\n{f}\n\np2"


def test_with_no_place_inside_that_keeps_the_page_it_goes_at_the_end(monkeypatch):
    from scrap.store import placing

    monkeypatch.setattr(placing, "_keeps", lambda *a: False)
    assert placed_after("- a\n- b\n\nend", "a", [E]) == f"- a\n- b\n\nend\n\n{E}"


def test_after_must_occur_once():
    for after, why in (("dog", "is not in"), ("aa", "more than once"), (" ", "empty")):
        with pytest.raises(InvalidError, match=why):
            placed_after("aaa cat", after, [E])


@pytest.mark.timing  # run alone: see conftest.py
def test_a_long_line_of_quote_marks_and_spaces_is_placed_quickly():
    """The list-item and quote patterns are possessive: linear on a 1 MB line."""
    import time

    body = "- a\n" + "> " * 250_000 + " \t" * 100_000 + "x"
    begin = time.monotonic()
    placed_after(body, "x", [E])
    assert (
        time.monotonic() - begin < 10
    )  # the parse dominates; quadratic took far longer
