# ruff: noqa: E501
"""Where add_svg's and the upload's after puts an embed (#480): right after the
line the passage ends on, inside its list item or quote; after a block that cannot
be split. The page's blocks stay as they were (checked by parsing it)."""

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


def holder(text):
    """The list items and quotes the embed's paragraph is in."""
    stack = []
    for t in MD.parse(text):
        if t.type in CONTAINERS:
            stack.append(t.type)
        elif t.type in ("list_item_close", "blockquote_close"):
            stack.pop()
        elif t.type == "inline" and t.content.strip() == E:
            return stack
    raise AssertionError("no embed paragraph")


EXAM_LINES = "Q3 A ladder leans on a wall.\n(a) Find the height.\nAnswer: 4 m\n(b) Find the angle.\nAnswer: 30°\n\nQ4"
EXAM_LIST = (
    "Q3\n\n1. Show that x = 2.\n   Answer: shown\n2. Find y.\n   Answer: 5\n\nQ4"
)
CASES = [
    # a paragraph is split after the line (the exam layout of (a)/(b) lines)
    (
        "para",
        "Q1 find x\nWorking:\n\nQ2",
        "find x",
        f"Q1 find x\n\n{E}\n\nWorking:\n\nQ2",
        [],
    ),
    (
        "exam lines",
        EXAM_LINES,
        "(a) Find the height.",
        f"Q3 A ladder leans on a wall.\n(a) Find the height.\n\n{E}\n\nAnswer: 4 m\n(b) Find the angle.\nAnswer: 30°\n\nQ4",
        [],
    ),
    ("end", "Q1 find x", "find x", f"Q1 find x\n\n{E}", []),
    ("end newline", "Q1 find x\n", "find x\n", f"Q1 find x\n\n{E}", []),
    # a list item keeps it, indented as a continuation; the list goes on
    (
        "exam list",
        EXAM_LIST,
        "Show that x = 2.",
        f"Q3\n\n1. Show that x = 2.\n\n   {E}\n\n   Answer: shown\n2. Find y.\n   Answer: 5\n\nQ4",
        ["list_item_open"],
    ),
    (
        "nested",
        "- a\n  - b\n    more b\n  - c\n- d",
        "- b",
        f"- a\n  - b\n\n    {E}\n\n    more b\n  - c\n- d",
        ["list_item_open", "list_item_open"],
    ),
    (
        "lazy line",
        "1. a\nlazy\n2. b",
        "1. a",
        f"1. a\n\n   {E}\n\n   lazy\n2. b",
        ["list_item_open"],
    ),
    (
        "ATX in a list",
        "- a\n  # h\n  b\n\nend",
        "# h",
        f"- a\n  # h\n\n  {E}\n\n  b\n\nend",
        ["list_item_open"],
    ),
    # a quote keeps it, quoted; two quotes stay two
    (
        "quote",
        "> q1\n> q2\n\nend",
        "q1",
        f"> q1\n>\n> {E}\n>\n> q2\n\nend",
        ["blockquote_open"],
    ),
    (
        "lazy quote",
        "> q1\nlazy\n\nend",
        "q1",
        f"> q1\n>\n> {E}\n>\n> lazy\n\nend",
        ["blockquote_open"],
    ),
    (
        "two quotes",
        "> q1\n\n> q2",
        "q1",
        f"> q1\n>\n> {E}\n\n> q2",
        ["blockquote_open"],
    ),
    # blocks that cannot be split: after their end
    (
        "fence",
        "```\nx = 1\n\ny = 2\n```\nafter",
        "x = 1",
        f"```\nx = 1\n\ny = 2\n```\n\n{E}\n\nafter",
        [],
    ),
    (
        "math fence",
        "Q\n\n```math\na\n\nb\n```\nend",
        "```math\na",
        f"Q\n\n```math\na\n\nb\n```\n\n{E}\n\nend",
        [],
    ),
    (
        "indented code",
        "para\n\n    code1\n\n    code2\n\nend",
        "code1",
        f"para\n\n    code1\n\n    code2\n\n{E}\n\nend",
        [],
    ),
    (
        "table",
        "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\nnext",
        "| 1 | 2 |",
        f"| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n{E}\n\nnext",
        [],
    ),
    (
        "table in a list",
        "- item\n\n  | a | b |\n  |---|---|\n  | 1 | 2 |\n\n- item2",
        "| 1 | 2 |",
        f"- item\n\n  | a | b |\n  |---|---|\n  | 1 | 2 |\n\n  {E}\n\n- item2",
        ["list_item_open"],
    ),
    (
        "display maths",
        "Q\n\n$$\na=1\n\nb=2\n$$\n\nend",
        "a=1",
        f"Q\n\n$$\na=1\n\nb=2\n$$\n\n{E}\n\nend",
        [],
    ),
    (
        "amsmath",
        "Q\n\n\\begin{align}\na\n\nb\n\\end{align}\n\nend",
        "a\n\nb",
        f"Q\n\n\\begin{{align}}\na\n\nb\n\\end{{align}}\n\n{E}\n\nend",
        [],
    ),
    ("setext", "Title\n=====\nbody", "Title", f"Title\n=====\n\n{E}\n\nbody", []),
    ("ATX", "# Q1\nFind x", "Q1", f"# Q1\n\n{E}\n\nFind x", []),
    # a split that would change the page (a line that would start a list): after the paragraph
    ("no new list", "Q1 x\n2. y\n\nend", "Q1", f"Q1 x\n2. y\n\n{E}\n\nend", []),
    ("inline code", "a `x\ny` b\n\nc", "a `x", f"a `x\ny` b\n\n{E}\n\nc", []),
]


@pytest.mark.parametrize(
    "name, body, after, placed, inside", CASES, ids=[c[0] for c in CASES]
)
def test_the_embed_goes_after_the_line_and_the_page_keeps_its_shape(
    name, body, after, placed, inside
):
    out = placed_after(body, after, [E])
    assert out == placed
    assert blocks(out) == blocks(body)
    assert holder(out) == inside


def test_several_embeds_go_together():
    out = placed_after("- a\n- b", "a", [E, E.replace("d", "f")])
    assert out == f"- a\n\n  {E}\n\n  ![f](e)\n\n- b"
    assert blocks(out) == blocks("- a\n- b")


def test_after_must_occur_once():
    for after, why in (("dog", "is not in"), ("aa", "more than once"), (" ", "empty")):
        with pytest.raises(InvalidError, match=why):
            placed_after("aaa cat", after, [E])
