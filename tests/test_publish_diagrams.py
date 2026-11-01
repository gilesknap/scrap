"""A page's Mermaid diagrams published (#525; docs/reference/public-site.md,
"Diagrams"): the PWA's two SVGs for each, light and dark, sanitised and scrubbed by
scrap, published as img-*.svg beside the page, counted in the caps, and their words
indexed for search; and a code block's /api/ paths left as written (#529)."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from publishhelp import Site, configure, page
from scrap import svg
from scrap.app import create_app
from scrap.publish import derived
from scrap.publish.diagrams import clean_diagram
from scrap.publish.errors import CheckError
from scrap.publish.kept import Kept
from scrap.publish.links import scrub_code
from scrap.publish.search import index_text
from scrap.store import new_ulid

OWN = "https://scrap.example.org"  # scrap's own address, never published
REAL = (Path(__file__).parent / "data" / "mermaid_light.svg").read_text()


@pytest.fixture
def site(tmp_path, monkeypatch):
    running = Site(tmp_path / "site")
    configure(monkeypatch, tmp_path, running)
    monkeypatch.setenv("SCRAP_PUBLIC_URL", OWN)
    yield running
    running.stop()


@pytest.fixture
def client(tmp_path, site):
    return TestClient(create_app(tmp_path / "data"))


def drawn(label: str = "Phone", fill: str = "#eee") -> str:
    """An SVG as Mermaid draws one with SVG labels."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" id="d" width="120" height="40"'
        ' viewBox="0 0 120 40"><style>#d{font-family:system-ui;fill:#333}</style>'
        f'<g class="node"><rect width="120" height="40" style="fill:{fill}"></rect>'
        f'<text y="20"><tspan x="0" dy="1.1em">{label}</tspan></text></g></svg>'
    )


def figure(key: str = "1", dark: bool = True) -> str:
    """A diagram as the publish mode writes it."""
    themes = ("light", "dark") if dark else ("light",)
    imgs = "".join(
        f'<img class="{t}" src="scrap-diagram:{key}-{t}" alt="Diagram">' for t in themes
    )
    return f'<figure class="diagram">{imgs}</figure>'


def made(client) -> dict:
    data = {"id": new_ulid(), "text": "```mermaid\nflowchart LR\n  A --> B\n```"}
    ref = client.post("/api/captures", json=data).json()
    return client.patch(f"/api/pages/{ref['slug']}", json={"public": True}).json()


def publish(client, p: dict, body: str, diagrams: list[dict]):
    ask = {"html": page(body, title=p["title"]), "base_rev": p["rev"],
           "confirmed": True, "diagrams": diagrams}  # fmt: skip
    return client.put(f"/api/pages/{p['slug']}/published", json=ask)


def test_a_diagram_is_published_in_both_themes(client, site):
    p = made(client)
    sent = [{"key": "1", "light": REAL, "dark": drawn("Dark one", "#222")}]
    r = publish(client, p, figure(), sent)
    assert r.status_code == 200, r.text
    assert r.json()["files"] == 2
    unit = site.folder / "www" / "p" / p["slug"]
    names = sorted(f.name for f in unit.iterdir() if f.suffix == ".svg")
    assert len(names) == 2
    assert all(re.fullmatch(r"img-[12]-[0-9a-f]{10}\.svg", n) for n in names)
    index = (unit / "index.html").read_text()
    shown = re.findall(r'<img class="(light|dark)" src="/p/[^/]+/(img-[^"]+)"', index)
    assert [t for t, _ in shown] == ["light", "dark"]
    assert {n for _, n in shown} == set(names)
    assert "scrap-diagram" not in index
    light = (unit / dict(shown)["light"]).read_text()
    # Mermaid's drawing as it was: its labels, its style, its size
    assert svg.text_of(light.encode()).split("\n") == [
        "share",
        "Claude",
        "Phone",
        "Offline queue",
        "api/captures",
        "SQLite",
        "Ingest",
    ]
    assert "<style>" in light and 'width="906"' in light
    assert "Dark one" in (unit / dict(shown)["dark"]).read_text()
    # search reads the light one's words, once
    indexed = derived._TEXTS[p["slug"]][1]
    assert "Offline queue api/captures" in indexed and "Dark one" not in indexed


def test_a_diagram_is_sanitised_and_scrubbed(monkeypatch) -> None:
    monkeypatch.setenv("SCRAP_PUBLIC_URL", OWN)
    nasty = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 9" onload="alert(1)">'
        "<script>alert(2)</script>"
        '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">HTML</div>'
        "</foreignObject>"
        '<a href="https://evil.example/x"><text>linked</text></a>'
        '<image href="https://evil.example/x.png"></image>'
        f'<text aria-label="{OWN}/p/secret">API[/api/captures/] and'
        f" {OWN}/p/secret and /api/blobs/abc</text></svg>"
    )
    out = clean_diagram(nasty).decode()
    for gone in ("script", "alert", "foreignObject", "HTML", "evil.example",
                 "onload", "scrap.example.org", "/api/blobs/"):  # fmt: skip
        assert gone not in out, gone
    assert "API[/api/captures/] and a private link and a private link" in out
    assert 'aria-label="a private link"' in out


def test_a_style_naming_scrap_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("SCRAP_PUBLIC_URL", OWN)
    styled = drawn().replace("fill:#333", "fill:#333;--x:scrap.example.org")
    with pytest.raises(CheckError) as refused:
        clean_diagram(styled)
    assert refused.value.code == "bad_diagram"


@pytest.mark.parametrize("bad", ["<svg", "<html></html>", "<svg><![CDATA[x]]></svg>"])
def test_what_is_not_an_svg_is_refused(bad: str) -> None:
    with pytest.raises(CheckError) as refused:
        clean_diagram(bad)
    assert refused.value.code == "bad_diagram"


def test_a_diagram_must_be_shown_whole_and_sent(client):
    p = made(client)
    one = [{"key": "1", "light": drawn(), "dark": drawn()}]
    no = publish(client, p, figure(), [])
    assert (no.status_code, no.json()["error"]) == (422, "bad_diagram")
    half = publish(client, p, figure(dark=False), one)
    assert (half.status_code, half.json()["error"]) == (422, "bad_diagram")
    extra = publish(client, p, figure(), [*one, {**one[0], "key": "2"}])
    assert (extra.status_code, extra.json()["error"]) == (422, "bad_diagram")
    twice = publish(client, p, figure(), one * 2)
    assert (twice.status_code, twice.json()["error"]) == (422, "bad_request")
    swapped = figure().replace('class="dark"', 'class="light x"', 1)
    wrong = publish(client, p, swapped, one)
    assert (wrong.status_code, wrong.json()["error"]) == (422, "bad_html")
    linked = figure() + '<a href="scrap-diagram:1-light">x</a>'
    assert publish(client, p, linked, one).status_code == 422
    ok = publish(client, p, figure(), one)
    assert ok.status_code == 200, ok.text


def test_a_diagram_counts_toward_the_caps(client, monkeypatch):
    from scrap.publish import files as publish_files

    p = made(client)
    monkeypatch.setattr(publish_files, "MAX_FILES", 1)  # two images: one too many
    r = publish(client, p, figure(), [{"key": "1", "light": drawn(), "dark": drawn()}])
    assert (r.status_code, r.json()["error"]) == (422, "too_many_files")


def test_search_reads_a_diagrams_words_once() -> None:
    wrapped = drawn("Offline queue").replace(
        '<tspan x="0" dy="1.1em">Offline queue</tspan>',
        '<tspan class="text-outer-tspan row"><tspan>A label that</tspan></tspan>'
        '<tspan class="text-outer-tspan row"><tspan>would</tspan>'
        "<tspan> wrap</tspan></tspan>",
    )
    assert wrapped != drawn("Offline queue")
    files = {"img-1-0123456789.svg": wrapped.encode(),
             "img-2-0123456789.svg": drawn("Dark words").encode()}  # fmt: skip
    html = (
        '<p>Before</p><figure class="diagram">'
        '<img class="light" src="/p/a/img-1-0123456789.svg" alt="Diagram">'
        '<img class="dark" src="/p/a/img-2-0123456789.svg" alt="Diagram">'
        "</figure><p>After</p>"
    )
    got = index_text(html, lambda n: files.get(n, b""))
    assert got == "Before A label that would wrap After"
    assert index_text(html) == "Before After"


def test_a_kept_file_is_read_by_a_plain_name_only(tmp_path) -> None:
    kept = Kept(tmp_path)
    kept.write("a", {"index.html": b"x", "img-1-0123456789.svg": b"<svg/>"}, {}, "d")
    assert kept.file("a", "img-1-0123456789.svg") == b"<svg/>"
    for bad in ("", "..", "../a/index.html", "meta.json", "x/../index.html"):
        assert kept.file("a", bad) == b""


def test_code_keeps_its_api_paths(monkeypatch) -> None:
    monkeypatch.setenv("SCRAP_PUBLIC_URL", OWN)
    assert scrub_code(f"B[{OWN}/p/x] C") == "B[a private link] C"
    assert scrub_code("API[/api/captures/]") == "API[/api/captures/]"
    assert (
        scrub_code("GET https://other.example/api/x")
        == "GET https://other.example/api/x"
    )
    assert scrub_code("/API/Blobs/abc") == "a private link"


def test_an_address_mermaid_wrapped_is_hidden_whole(monkeypatch) -> None:
    monkeypatch.setenv("SCRAP_PUBLIC_URL", OWN)
    split = drawn().replace(
        '<tspan x="0" dy="1.1em">Phone</tspan>',
        '<tspan class="row">see https://scrap.exam</tspan>'
        '<tspan class="row">ple.org/p/secret-page</tspan>',
    )
    out = clean_diagram(split).decode()
    assert "exam" not in out and "secret-page" not in out
    assert '<text y="20">a private link</text>' in out
    blobs = drawn().replace("Phone", "/api/blo</tspan><tspan>bs/abc")
    assert "bs/abc" not in clean_diagram(blobs).decode()


def test_a_long_word_is_scrubbed_in_linear_time(monkeypatch) -> None:
    import time

    monkeypatch.setenv("SCRAP_PUBLIC_URL", OWN)
    start = time.perf_counter()
    assert scrub_code("z" * 400_000) == "z" * 400_000
    assert time.perf_counter() - start < 2  # was quadratic: minutes
