# ruff: noqa: E501
"""Where add_svg's and the upload's after puts an embed (#480): after the Markdown
block the passage ends in, never inside one."""

import pytest

from scrap.store import InvalidError
from scrap.store.placing import placed_after

E = "![d](e)"


@pytest.mark.parametrize(
    "body, after, placed",
    [
        ("Q1 find x\n\nQ2", "find x", f"Q1 find x\n\n{E}\n\nQ2"),
        ("Q1 find x", "find x", f"Q1 find x\n\n{E}"),
        ("Q1 find x\n", "find x\n", f"Q1 find x\n\n{E}"),
        # a paragraph is not split: the embed follows all of it
        ("Q1\nfind x\nmore\n\nQ2", "Q1\nfind", f"Q1\nfind x\nmore\n\n{E}\n\nQ2"),
        # a fenced code block, even with blank lines in it, and an unclosed one
        ("```\nx = 1\n\ny = 2\n```\nafter", "x = 1", f"```\nx = 1\n\ny = 2\n```\n\n{E}\n\nafter"),
        ("~~~~\na\n~~~\nb", "a", f"~~~~\na\n~~~\nb\n\n{E}"),
        ("intro\n```\ncode\n```", "intro", f"intro\n\n{E}\n\n```\ncode\n```"),
        # a table
        ("| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\nnext", "| 1 | 2 |",
         f"| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n{E}\n\nnext"),
        # lists: ordered, nested, loose (blank lines between items), with code
        ("1. first\n2. second\n3. third", "first", f"1. first\n2. second\n3. third\n\n{E}"),
        ("- a\n  - b\n  - c\n\nafter", "b", f"- a\n  - b\n  - c\n\n{E}\n\nafter"),
        ("1. a\n\n2. b\n\n   more b\n\nend", "a", f"1. a\n\n2. b\n\n   more b\n\n{E}\n\nend"),
        ("- a\n  ```\n  x\n\n  ```\n- b", "a", f"- a\n  ```\n  x\n\n  ```\n- b\n\n{E}"),
        # a quote; headings (setext ends at its underline, ATX is a line)
        ("> q1\n> q2\n\nnext", "q1", f"> q1\n> q2\n\n{E}\n\nnext"),
        ("Title\n=====\nbody", "Title", f"Title\n=====\n\n{E}\n\nbody"),
        ("# Q1\nFind x", "Q1", f"# Q1\n\n{E}\n\nFind x"),
        ("Find x\n# Q2", "Find", f"Find x\n\n{E}\n\n# Q2"),
    ],
)  # fmt: skip
def test_the_embed_goes_after_the_block(body, after, placed):
    assert placed_after(body, after, [E]) == placed


def test_after_must_occur_once():
    for after, why in (("dog", "is not in"), ("aa", "more than once"), (" ", "empty")):
        with pytest.raises(InvalidError, match=why):
            placed_after("aaa cat", after, [E])
