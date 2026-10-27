"""markdown.py: page text parsed as Markdown, for the search index and the importer."""

import time

import pytest

from scrap import markdown
from scrap.markdown import Link, plain, rewrite


def tagged(text: str) -> str:
    """Each link as <kind:target|label>, with ! for an embed and T in a table."""

    def show(link: Link) -> str:
        marks = ("!" if link.embed else "") + ("T" if link.in_table else "")
        return f"<{link.kind}:{link.target}|{link.label}{marks}>"

    return rewrite(text, show)


def test_plain_text_has_words_not_markup():
    text = (
        "# Title\n\nSee [the docs](https://docs.example.org/guide), **bold**,"
        " ~~gone~~ and [[other|a label]] [[bare]] ![a chart](/api/blobs/x)\n"
    )
    assert plain(text) == "Title\nSee the docs, bold, gone and a label bare a chart"


def test_plain_text_of_tables_lists_code_and_html():
    text = (
        "| Name | [Site](https://e.com/x) |\n|---|:-:|\n| `a\\|b` | two |\n\n"
        "- one\n  - nested **deep**\n    1. numbered\n\n"
        "```python\nx = [[not_a_link]]  # [y](z)\n```\n\n"
        "    indented [code](q)\n\n"
        "<b>bold</b> <script>x</script>\n\n> quoted [[q|said]]\n\n"
        "Note[^1].\n\n[^1]: The footnote.\n"
    )
    words = plain(text).split()
    for word in ("Name", "Site", "a|b", "two", "one", "nested", "deep", "numbered",
                 "[[not_a_link]]", "[y](z)", "[code](q)", "<b>bold</b>", "said",
                 "footnote."):  # fmt: skip
        assert word in words
    assert "https://e.com/x" not in plain(text)


def test_rewrite_skips_code_and_finds_links_everywhere_else():
    text = (
        "![[my pic.png]] ![alt](a%20b.png) [sec](dup.md#part) [[#A heading]]\n"
        "`[[code]]` and ``[x](y.md)``\n"
        "```\n```js\n[[fenced]]\n```\n"
        "> quoted [a](b.md)\n> more [[x]]\n\n"
        "- item [l](m.md)\n  - deep [[y|why]]\n\n"
        "| h | [[t]] |\n|--|--|\n| [[u\\|v]] | [w](z.md) |\n\n"
        "[x [y](z)](q) [![](B)](https://e.com) <b>[[h]]</b>\n"
    )
    assert tagged(text) == (
        "<wiki:my pic.png|!> <image:a%20b.png|alt!> <link:dup.md#part|sec>"
        " <wiki:#A heading|>\n"
        "`[[code]]` and ``[x](y.md)``\n"
        "```\n```js\n[[fenced]]\n```\n"
        "> quoted <link:b.md|a>\n> more <wiki:x|>\n\n"
        "- item <link:m.md|l>\n  - deep <wiki:y|why|>\n\n"
        "| h | <wiki:t|T> |\n|--|--|\n| <wiki:u|v|T> | <link:z.md|wT> |\n\n"
        "[x <link:z|y>](q) [<image:B|!>](https://e.com) <b><wiki:h|></b>\n"
    )


def test_rewrite_keeps_what_it_is_told_to_and_the_rest_as_typed():
    text = "keep [a](b.md) and [[c]]\r\nnext"
    assert rewrite(text, lambda link: None) == "keep [a](b.md) and [[c]]\nnext"


@pytest.mark.timing  # run alone: see conftest.py
@pytest.mark.parametrize(
    "pattern",
    [
        "[",
        "[[",
        "[a](",
        "![",
        "`",
        "*a",
        "_a ",
        "<",
        "> ",
        "- ",
        "[[a|",
        "\\",
        "x [[y]]\n",
        "| [[y]] |\n",
    ],
)
def test_hostile_text_takes_linear_time(pattern):
    """Twice the text takes about twice as long, not four times."""

    def took(n: int) -> float:
        text = pattern * (n // len(pattern))
        start = time.process_time()
        plain(text)
        rewrite(text, lambda link: None)
        return time.process_time() - start

    # CPU time, not wall time: a busy runner descheduling the test does not count
    def fastest(n: int) -> float:
        # The minimum of several runs: a noisy CI box only ever makes a run slower
        return min(took(n) for _ in range(5))

    took(10_000)  # warm-up: imports, caches and the allocator
    # Start where a run takes long enough (0.1 s) that timer and scheduling noise is
    # small beside it, so a pure ratio can be used: linear is 4x for 4x the text,
    # quadratic 16x. The line is 12x, not halfway: coverage tracing and a busy runner
    # made linear text measure past 8x from a 40 ms start (#269); quadratic still fails
    # it by a wide margin
    n = 10_000
    while took(n) < 0.1 and n < 2_560_000:  # one run a size, to find it
        n *= 2
    small = fastest(n)
    ratio = fastest(4 * n) / small
    assert ratio < 12, f"{ratio:.1f}x for 4x the text"


@pytest.mark.timing  # run alone: see conftest.py
def test_a_paragraph_of_many_lines_is_rewritten_in_linear_time():
    text = "x [[y]]\n" * 20_000  # one paragraph: every link maps back to its line
    start = time.monotonic()
    out = rewrite(text, lambda link: f"<{link.target}>")
    assert out == "x <y>\n" * 20_000
    assert time.monotonic() - start < 10  # about 9 s per 20k lines was quadratic


def test_a_block_that_cannot_be_mapped_back_is_kept_and_told(monkeypatch):
    """A block whose lines aren't found as typed (none is known today: the parser's
    tab expansion was the risk) keeps its links as typed, and says where."""
    monkeypatch.setattr(markdown, "_source", lambda *args: None)
    told: list[int] = []
    text = "first\n\nsecond [[b]]\nthird [[d]]\n"
    assert rewrite(text, lambda link: "X", told.append) == text
    assert told == [3]


@pytest.mark.timing  # run alone: see conftest.py
def test_a_megabyte_page_is_indexed():
    words = (
        "Some *text* with [a link](http://x.com), `code` and [[a-page|a label]]\n\n"
        "- item\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
    )
    text = words * (1_000_000 // len(words))
    start = time.monotonic()
    assert "a label" in plain(text)
    assert time.monotonic() - start < 30  # about 3 s on the canary
