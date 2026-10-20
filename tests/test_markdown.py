"""markdown.py: page text parsed as Markdown, for the search index and the importer."""

import time
from contextlib import closing

import pytest

from scrap.markdown import Link, plain, rewrite
from scrap.store import Store, connect, migrations


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


@pytest.mark.parametrize(
    "pattern",
    ["[", "[[", "[a](", "![", "`", "*a", "_a ", "<", "> ", "- ", "[[a|", "\\"],
)
def test_hostile_text_takes_linear_time(pattern):
    """Twice the text takes about twice as long, not four times."""

    def took(n: int) -> float:
        text = pattern * (n // len(pattern))
        start = time.monotonic()
        plain(text)
        rewrite(text, lambda link: None)
        return time.monotonic() - start

    small, large = took(10_000), took(40_000)
    assert large < 8 * small + 0.5


def test_a_megabyte_page_is_indexed():
    words = (
        "Some *text* with [a link](http://x.com), `code` and [[a-page|a label]]\n\n"
        "- item\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
    )
    text = words * (1_000_000 // len(words))
    start = time.monotonic()
    assert "a label" in plain(text)
    assert time.monotonic() - start < 30  # about 3 s on the canary


def test_migration_4_reindexes_pages_with_the_parser(tmp_path):
    db = tmp_path / "scrap.db"
    with closing(connect(db)) as conn:
        script = "".join(migrations()[:3])
        conn.executescript(f"BEGIN; {script} PRAGMA user_version = 3; COMMIT;")
        conn.execute(
            "INSERT INTO page (id, slug, title, body, fields, created_at, updated_at)"
            " VALUES ('P', 'p', 'T', '| cell | `[[codeword]]` |\n|-|-|\n| x | y |',"
            " '{}', 'x', 'x')"
        )
        conn.execute("INSERT INTO chunk (page_id, ord, text) VALUES ('P', 0, 'old')")
    store = Store(tmp_path)
    store.migrate()
    assert [h["slug"] for h in store.search("codeword", 5)] == ["p"]
    assert store.search("old", 5) == []
    with closing(connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations())
