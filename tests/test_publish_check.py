"""The check of an uploaded page (scrap.publish.checker; docs/reference/public-site.md,
"What scrap sends for a page"): what passes, what is refused, and KaTeX's own markup.

tests/data/katex_corpus.json is KaTeX 0.16.47's renderToString, with the PWA's options
(web/src/math.ts: trust false, throwOnError true, strict "ignore"), of formulas that
use every kind of markup it writes: fractions, roots and stretchy symbols (SVG),
\\cancel (SVG lines), \\boxed and \\fcolorbox (borders), \\colorbox and \\color
(colours), arrays with | and : rules and \\hline / \\hdashline (border styles),
matrices, cases, aligned and alignat (mtd classes), \\boldsymbol and \\pmb
(text-shadow), the font commands, accents, phantoms and smash, kerns and \\rule,
\\operatorname and \\pmod (MathML inside mtext and mo), sizes and styles, \\tag, {CD}
and the extensible arrows, each inline and displayed. tests/data/katex_corpus.mjs
renders it again (from web/, after npm ci) when KaTeX is upgraded."""

import json
from pathlib import Path

import pytest

from publishhelp import page
from scrap.publish.checker import CSP, check
from scrap.publish.errors import CheckError

CORPUS = json.loads((Path(__file__).parent / "data" / "katex_corpus.json").read_text())
SHA = "a" * 64
PUBLIC = {"open-page"}


def ok(body: str, **kw) -> object:
    return check(page(body, **kw), PUBLIC.__contains__)


def refused(text: str) -> str:
    with pytest.raises(CheckError) as e:
        check(text, PUBLIC.__contains__)
    return e.value.detail


def test_the_corpus_is_katex_0_16_47():
    assert CORPUS["katex"] == "0.16.47"
    assert CORPUS["options"] == {
        "throwOnError": True, "trust": False, "strict": "ignore"
    }  # fmt: skip
    assert len(CORPUS["cases"]) > 80


@pytest.mark.parametrize(
    "case", CORPUS["cases"], ids=lambda c: f"{c['tex'][:30]}-{c['display']}"
)
def test_katex_markup_passes(case):
    found = ok(f"<p>{case['html']}</p>", maths=True)
    assert found.maths  # type: ignore[attr-defined]


ALLOWED = [
    '<h1 id="intro">Intro</h1><p>Plain <b>bold</b> <em>em</em> <code>x</code></p>',
    '<p><a href="https://example.org/x?y=1#z">out</a> <a href="http://a.b/">b</a></p>',
    '<p><a href="mailto:me@example.org">mail</a> <a href="#fn1">[1]</a></p>',
    '<p><a href="/p/open-page">a public page</a> <a href="/t/tag-1a2b3c4d">t</a></p>',
    "<p><span>a private page's label</span></p>",
    f'<figure><img src="scrap-blob:{SHA}" alt="IMG_2041.jpg"></figure>',
    f'<p><img src="scrap-blob:{SHA}" alt=""><a href="scrap-blob:{SHA}">photo</a></p>',
    '<p><a class="chip" href="scrap-tag:personal%2Ffamily">personal/family</a></p>',
    '<table><thead><tr><th colspan="2">h</th></tr></thead>'
    '<tbody><tr><td rowspan="12">x</td></tr></tbody></table>',
    "<details open><summary>s</summary><p>d</p></details>",
    '<ol><li id="fn1">note <a href="#fnref1" id="fnref1">back</a></li></ol>',
    '<pre><code class="language-mermaid">graph TD; A--&gt;B</code></pre>',
    '<p dir="rtl">שלום</p><!-- a comment -->',
    "<blockquote><p>q</p></blockquote><hr><br>",
]


@pytest.mark.parametrize("body", ALLOWED)
def test_allowed(body):
    ok(body)


def test_what_a_page_names_is_collected():
    found = ok(
        f'<p><img src="scrap-blob:{SHA}" alt="x"><a href="scrap-blob:{"b" * 64}">f</a>'
        f'<a href="scrap-blob:{SHA}">again</a><a href="scrap-tag:a%20b">a b</a>'
        '<a href="/p/open-page">p</a></p>'
    )
    assert found.blobs == [(SHA, "img"), ("b" * 64, "a"), (SHA, "a")]  # type: ignore[attr-defined]
    assert found.tags == ["a b"]  # type: ignore[attr-defined]
    assert found.pages == {"open-page"}  # type: ignore[attr-defined]
    assert not found.maths  # type: ignore[attr-defined]


REFUSED_BODIES = {
    "script": "<script>alert(1)</script>",
    "script in svg": '<span class="katex"><svg><script>alert(1)</script></svg></span>',
    "style element": "<style>p{color:red}</style>",
    "on* attribute": '<p onclick="alert(1)">x</p>',
    "on* in katex": '<span class="katex"><span onmouseover="x()">x</span></span>',
    "img onerror": f'<img src="scrap-blob:{SHA}" onerror="alert(1)">',
    "javascript:": '<a href="javascript:alert(1)">x</a>',
    "javascript: entity-encoded": '<a href="&#106;avascript:alert(1)">x</a>',
    "javascript: hex entities": '<a href="&#x6a;&#x61;vascript&colon;alert(1)">x</a>',
    "javascript: with a tab": '<a href="java&#9;script:alert(1)">x</a>',
    "data:": '<a href="data:text/html,<script>x</script>">x</a>',
    "vbscript:": '<a href="vbscript:x">x</a>',
    "svg use": '<span class="katex"><svg><use href="#x"></use></svg></span>',
    "svg foreignObject": '<span class="katex"><svg><foreignObject><p>x</p>'
    "</foreignObject></svg></span>",
    "svg a": '<span class="katex"><svg><a href="https://x">x</a></svg></span>',
    "svg style": '<span class="katex"><svg><style>*{}</style></svg></span>',
    "xlink:href": '<span class="katex"><svg><path xlink:href="#x" d="M0"/>'
    "</svg></span>",
    "svg outside katex": '<svg><path d="M0"/></svg>',
    "math outside katex": "<math><mi>x</mi></math>",
    "style outside katex": '<p style="color:red">x</p>',
    "style with url(": '<span class="katex"><span style="background-color:url(x)">'
    "x</span></span>",
    "a style property katex never writes": '<span class="katex">'
    '<span style="position:fixed">x</span></span>',
    "url( in an svg attribute": '<span class="katex"><svg width="url(x)"></svg></span>',
    "url( in a MathML attribute": '<span class="katex"><math><mi mathcolor="url(x)">x'
    "</mi></math></span>",
    "an attribute twice": '<p class="a" class="b">x</p>',
    "a CDATA section": "<p><![CDATA[ x ]]></p>",
    "a CDATA section in svg": '<span class="katex"><svg><![CDATA[x]]></svg></span>',
    "a processing instruction": "<p><?php x ?></p>",
    "template": "<template><p>x</p></template>",
    "iframe": '<iframe src="https://x"></iframe>',
    "form": "<form><p>x</p></form>",
    "object": '<object data="x"></object>',
    "a stray placeholder in text": f"<p>scrap-blob:{SHA}</p>",
    "a stray tag placeholder in text": "<p>scrap-tag:x</p>",
    "a placeholder in alt": f'<img src="scrap-blob:{SHA}" alt="scrap-blob:{SHA}">',
    "a placeholder in a class": f'<p class="scrap-blob:{SHA}">x</p>',
    "a placeholder in a comment": f"<!-- scrap-blob:{SHA} --><p>x</p>",
    "an entity-encoded placeholder": f'<a href="scrap&#45;blob:{SHA}">x</a>',
    "a placeholder in a link": f'<a href="https://x.org/scrap-blob:{SHA}">x</a>',
    "an image from elsewhere": '<img src="https://x.org/a.png">',
    "an image as data:": '<img src="data:image/png;base64,AAAA">',
    "an image of the api": f'<img src="/api/blobs/{SHA}/preview?size=2048">',
    "a relative /api link": '<a href="/api/pages/x">x</a>',
    "/api on another host": '<a href="https://example.org/api/pages/x">x</a>',
    "/API on another host": '<a href="https://example.org/API/x">x</a>',
    "/api percent-encoded": '<a href="https://example.org/%61pi/x">x</a>',
    "scrap's own origin": '<a href="https://scrap.example.ts.net/p/x">x</a>',
    "scrap's own origin, upper case": '<a href="https://SCRAP.example.ts.net/">x</a>',
    "scrap's own origin, trailing dot": '<a href="https://scrap.example.ts.net./">x</a>',
    "scrap's own origin, another port": '<a href="http://scrap.example.ts.net:81/">x'
    "</a>",
    "userinfo": '<a href="https://user@example.org/">x</a>',
    "userinfo with a password": '<a href="https://u:p@example.org/">x</a>',
    "userinfo hiding scrap": '<a href="https://example.org@scrap.example.ts.net/">x'
    "</a>",
    "a protocol-relative link": '<a href="//example.org/x">x</a>',
    "a backslash link": '<a href="/\\example.org/x">x</a>',
    "a backslash in an absolute link": '<a href="https://example.org\\@x/">x</a>',
    "a private page": '<a href="/p/private-page">x</a>',
    "a relative link": '<a href="other">x</a>',
    "a heading id with a capital": '<h2 id="Intro">x</h2>',
    "an id on a p": '<p id="x">x</p>',
    "colspan too long": '<table><tr><td colspan="1000">x</td></tr></table>',
    "aria-hidden outside katex": '<span aria-hidden="true">x</span>',
    "an unknown element": "<marquee>x</marquee>",
    "input": '<input type="checkbox">',
    "a link element in the body": '<link rel="stylesheet" href="/assets/page.css">',
    "meta in the body": '<meta http-equiv="refresh" content="0;url=https://x">',
    "base": '<base href="https://x/">',
}


@pytest.mark.parametrize("body", REFUSED_BODIES.values(), ids=REFUSED_BODIES.keys())
def test_refused(body, monkeypatch):
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://scrap.example.ts.net:8446")
    refused(page(body))


def head(extra: str = "", csp: str = CSP, title: str = "<title>t</title>") -> str:
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
        f"{title}{extra}</head><body><p>x</p></body></html>"
    )


def test_the_head():
    check(head(), PUBLIC.__contains__)
    spaced = CSP.replace("; ", ";\n   ")  # whitespace normalised
    check(head(csp=spaced), PUBLIC.__contains__)
    assert "Content-Security-Policy" in refused(head(csp=CSP + "; script-src *"))
    assert "Content-Security-Policy" in refused(head().replace(
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">', ""
    ))  # fmt: skip
    assert "title" in refused(head(title=""))
    for extra in (
        '<link rel="stylesheet" href="/assets/other.css">',
        '<link rel="preload" href="/assets/page.css">',
        '<link rel="stylesheet" href="https://x.org/a.css">',
        '<meta name="referrer" content="unsafe-url">',
        "<style>p{}</style>",
        '<script src="/pagefind/pagefind.js"></script>',
        '<base href="/">',
        '<meta charset="utf-8">',  # twice
    ):
        refused(head(extra))


def test_the_document():
    assert "DOCTYPE" in refused(head().replace("<!DOCTYPE html>", ""))
    refused(head().replace("<!DOCTYPE html>", '<!DOCTYPE html PUBLIC "-//W3C">'))
    refused(head().replace('<html lang="en">', '<html lang="en" onload="x()">'))
    refused(head().replace("<body>", '<body onload="x()">'))
    refused(head().replace("<body>", '<body style="color:red">'))
    check(head().replace("<body>", '<body dir="ltr" lang="en">'), PUBLIC.__contains__)


PWA = sorted((Path(__file__).parent / "data" / "pwa_published").glob("*.html"))


@pytest.mark.parametrize("path", PWA, ids=lambda p: p.name)
def test_the_pwa_publish_modes_pages_pass(path):
    """Copies of web/tests/fixtures/published/*.html (feat-497-pwa, e5c56ced): what
    the PWA's publish mode writes. Its links to /p/ pages count as public here."""
    check(path.read_text(), lambda slug: True)


def test_site_links_and_a_neutralised_placeholder_in_text_pass():
    ok('<p><a href="/">All pages</a> <a href="/tags">Tags</a></p>')
    ok(f"<p>scrap-⁠blob:{SHA} and scrap-⁠tag:x as text</p>")
