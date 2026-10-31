"""SVG files (#480): sanitised on upload, their own preview, and read as text by
ingest (their words for search with no model; their markup to Claude, not pixels)."""

import io
import json
import zipfile
from contextlib import closing

import pytest

from scrap import ingest, svg
from scrap.store import InvalidError, Store, TooLargeError, connect, new_ulid
from test_ingest import Fake

NS = 'xmlns="http://www.w3.org/2000/svg"'
TRIANGLE = f"""<svg {NS} viewBox="0 0 200 120">
<title>Right-angled triangle</title><desc>Find the hypotenuse</desc>
<polygon points="10,110 190,110 10,10" fill="none" stroke="black"/>
<text x="90" y="118">12 <tspan>cm</tspan></text><text x="2" y="60">5 cm</text>
<text x="150" y="105">30°</text></svg>""".encode()
EVIL = f"""<svg {NS} xmlns:xlink="http://www.w3.org/1999/xlink" onload="alert(1)">
<script>alert(2)</script>
<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">html</div></foreignObject>
<a xlink:href="javascript:alert(3)"><text onclick="alert(4)">label</text></a>
<a href="https://evil.example/">link</a>
<image href="https://evil.example/track.png"/><image href="data:image/png;base64,AAAA"/>
<use href="#r"/><use href="https://evil.example/x.svg#r"/>
<set attributeName="href" to="javascript:alert(5)"/><animate attributeName="x"/>
<style>@import url(https://evil.example/a.css); .a{{fill:url(#g)}}
.b{{background:url(https://evil.example/b)}}</style>
<rect id="r" fill="url(https://evil.example/#g)" style="fill:url(#g)" width="1"/>
</svg>""".encode()
SCENE = {
    "kind": "diagram", "title": "Triangle", "tags": ["maths"],
    "description": "A right-angled triangle with sides 12 cm and 5 cm",
    "text": "something else", "elements": [{"type": "rectangle", "id": "a", "x": 1,
                                            "y": 1, "width": 5, "height": 5}],
}  # fmt: skip


def test_sanitise_keeps_the_drawing_and_drops_what_could_run_or_fetch():
    out = svg.sanitise(EVIL).decode()
    gone = ("script", "alert", "foreignObject", "<div", "onload", "onclick",
            "javascript", "evil.example", "<set", "<animate", "@import")  # fmt: skip
    for word in gone:
        assert word not in out, word
    for kept in ("<text>label</text>", 'href="#r"', 'fill="x-url()"',
                 'href="data:image/png;base64,AAAA"', ".a{fill:url(#g)}",
                 'style="fill:url(#g)"', ">link</a>"):  # fmt: skip
        assert kept in out, kept
    assert out.startswith(f"<svg {NS}")
    assert svg.sanitise(out.encode()).decode() == out  # stable: nothing more to drop


def test_a_doctype_entities_or_another_root_is_refused():
    bomb = (b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaa">'
            b'<!ENTITY b "&a;&a;&a;">]><svg ' + NS.encode()
            + b">&b;</svg>")  # fmt: skip
    subset = b'<!DOCTYPE svg [<!ATTLIST svg a CDATA "x">]><svg ' + NS.encode() + b"/>"
    for data, why in [
        (bomb, "DOCTYPE"),
        (subset, "DOCTYPE"),
        (b"<svg " + NS.encode() + b'><!ENTITY a "x"></svg>', "DOCTYPE"),
        (b"<svg " + NS.encode() + b">&a;</svg>", "undefined entity"),
        (b'<html xmlns="http://www.w3.org/1999/xhtml"/>', "root element"),
        (b'<svg xmlns="http://example.com/other"/>', "root element"),
        (b"not markup", "well-formed"),
        ("<svg/>".encode("utf-16"), "UTF-8"),
        (b"<svg>" * 200 + b"</svg>" * 200, "nests"),
    ]:
        with pytest.raises(InvalidError, match=why):
            svg.sanitise(data)
    with pytest.raises(TooLargeError):
        svg.sanitise(b"<svg " + NS.encode() + b">" + b" " * svg.MAX_SVG + b"</svg>")
    # no namespace, as a hand-written file: taken as SVG, and given one
    bare = svg.sanitise(b"<svg><rect/></svg>")
    assert bare == f"<svg {NS}><rect></rect></svg>".encode()


# As matplotlib writes it (savefig format="svg"), DOCTYPE, metadata and all
MATPLOTLIB = b"""<?xml version="1.0" encoding="utf-8" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
  "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg xmlns:xlink="http://www.w3.org/1999/xlink" width="460.8pt" height="345.6pt"
 viewBox="0 0 460.8 345.6" xmlns="http://www.w3.org/2000/svg" version="1.1">
 <metadata>
  <rdf:RDF xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:cc="http://creativecommons.org/ns#"
   xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
   <cc:Work><dc:type rdf:resource="http://purl.org/dc/dcmitype/StillImage"/>
    <dc:creator><cc:Agent><dc:title>Matplotlib v3.9.2, https://matplotlib.org/</dc:title>
    </cc:Agent></dc:creator></cc:Work>
  </rdf:RDF>
 </metadata>
 <defs>
  <style type="text/css">*{stroke-linejoin: round; stroke-linecap: butt}</style>
 </defs>
 <g id="figure_1">
  <g id="patch_1">
   <path d="M 0 345.6 L 460.8 345.6 L 460.8 0 L 0 0 z" style="fill: #ffffff"/>
  </g>
  <g id="axes_1">
   <g id="line2d_1">
    <defs><path id="m1e2f" d="M 0 0 L 0 3.5"
     style="stroke: #000000; stroke-width: 0.8"/>
    </defs>
    <g><use xlink:href="#m1e2f" x="57.6" y="307.584" style="stroke: #000000"/></g>
   </g>
   <g id="text_1"><text x="57.6" y="322" style="font: 10px 'DejaVu Sans'">0.0</text></g>
   <path d="M 57.6 307 L 414.7 41" clip-path="url(#p0a1b2c3)"
    style="fill: none; stroke: #1f77b4; stroke-width: 1.5"/>
  </g>
 </g>
 <defs><clipPath id="p0a1b2c3">
  <rect x="57.6" y="41.472" width="357.12" height="266.112"/>
 </clipPath></defs>
</svg>
"""


def test_a_matplotlib_svg_is_taken_with_its_doctype_dropped():
    out = svg.sanitise(MATPLOTLIB).decode()
    assert "DOCTYPE" not in out and "metadata" not in out and "rdf" not in out
    kept = ('href="#m1e2f"', 'clip-path="url(#p0a1b2c3)"', "stroke-linejoin: round",
            "font: 10px 'DejaVu Sans'", '<clipPath id="p0a1b2c3">')  # fmt: skip
    for word in kept:
        assert word in out, word
    assert svg.text_of(MATPLOTLIB) == "0.0"


H = f'<svg {NS} xmlns:xlink="http://www.w3.org/1999/xlink">'
BYPASSES = [  # each once fetched evil.example in a browser, or could
    '<style>svg{fill: url("#" x); background-image: url(http://evil.example/l.png);'
    ' --a: ")}</style>',
    """<rect style='fill: url("#" x); mask-image: url(http://evil.example/m.png);"""
    """ --a:"'/>""",
    '<rect style="fill: url(&apos;#&apos; x); filter: url(//evil.example/f#f)"/>',
    '<style>svg{background-image: image-set("http://evil.example/i.png" 1x)}</style>',
    "<style>svg{background: -webkit-image-set('https://evil.example/i.png' 1x)}"
    "</style>",
    "<style>svg{background: image-set(url(https://evil.example/i.png) 1x)}</style>",
    '<style>svg{background: src("https://evil.example/s.png")}</style>',
    '<rect fill="URL( http://evil.example/p#p )" filter="url(&#x27;x.svg#f&#x27;)"/>',
    '<a href="#x" ping="http://evil.example/ping"><text>x</text></a>',
    '<image src="http://evil.example/s.png"/>',
]


@pytest.mark.parametrize("markup", BYPASSES)
def test_no_url_out_of_the_file_survives(markup):
    out = svg.sanitise(f"{H}{markup}</svg>".encode()).decode()
    out = out.removeprefix(f"<svg {NS}>")
    assert "evil" not in out and "//" not in out and "x.svg" not in out, out


def test_no_escape_spells_a_url():
    out = svg.sanitise(
        f"{H}<style>a{{b:u\\72l(http://e.example/x)}}</style></svg>".encode()
    )
    assert b"url(" not in out and b"//e.example" not in out


def test_a_fragment_url_survives_in_any_spelling():
    css = "a{fill:url(#g)} b{fill:url( '#g' )} c{fill:URL(\"#g\")}"
    out = svg.sanitise(f"{H}<style>{css}</style></svg>".encode()).decode()
    assert "a{fill:url(#g)} b{fill:url( '#g' )} c{fill:url(\"#g\")}" in out


def test_its_words_are_title_desc_and_text():
    assert svg.text_of(TRIANGLE) == (
        "Right-angled triangle\nFind the hypotenuse\n12 cm\n5 cm\n30°"
    )
    assert svg.text_of(b"<svg/") == ""  # unreadable: no words, no error


def add(client, key, data, name="t.svg", mime="image/svg+xml", **form):
    return client.post(
        f"/api/pages/{key}/captures",
        data={"id": new_ulid(), **form},
        files=[("file", (name, data, mime))],
    )


def test_an_svg_added_in_the_pwa_is_stored_sanitised_and_is_its_own_preview(
    client, note
):
    ref = note("Geometry")
    r = add(client, ref["page_id"], EVIL)
    assert r.status_code == 201, r.text
    page = r.json()
    sha = page["captures"][1]["blobs"][0]["sha256"]
    assert page["body"].endswith(f"![](/api/blobs/{sha}/preview?size=2048)")
    assert page["added"][0]["download_url"] == f"/api/blobs/{sha}?download=1"
    stored = client.get(f"/api/blobs/{sha}")
    assert stored.content == svg.sanitise(EVIL)  # never the markup sent
    for size in (480, 2048):
        shown = client.get(f"/api/blobs/{sha}/preview?size={size}")
        assert shown.status_code == 200
        assert shown.headers["content-type"] == "image/svg+xml"
        assert shown.headers["content-security-policy"] == "sandbox"
        assert shown.headers["x-content-type-options"] == "nosniff"
        assert shown.content == stored.content
    assert client.get(f"/api/blobs/{sha}/preview?size=99").status_code == 422
    # an untyped part is typed by its name; a bad SVG is refused, nothing added
    assert add(client, ref["page_id"], TRIANGLE, mime="").status_code == 201
    assert add(client, ref["page_id"], b"<html/>").status_code == 422
    big = b"<svg " + NS.encode() + b">" + b" " * svg.MAX_SVG + b"</svg>"
    assert add(client, ref["page_id"], big).status_code == 413
    assert client.get(f"/api/pages/{ref['page_id']}").json()["rev"] == 3


def test_a_new_page_from_an_svg_capture(client):
    files = [("file", ("t.svg", EVIL, "image/svg+xml"))]
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    sha = page["captures"][0]["blobs"][0]["sha256"]
    assert b"script" not in client.get(f"/api/blobs/{sha}").content
    assert client.get(f"/api/blobs/{sha}/preview").status_code == 200


def test_a_download_with_previews_keeps_the_svg(client, note):
    ref = note("Geometry")
    add(client, ref["page_id"], TRIANGLE, name="tri.svg")
    r = client.get(f"/api/pages/{ref['page_id']}/download?photos=preview")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.read("files/tri.svg") == svg.sanitise(TRIANGLE)
        assert "(files/tri.svg)" in zf.read(f"{ref['slug']}.md").decode()


def test_ingest_reads_its_words_then_sends_claude_its_markup(tmp_path, client, note):
    ref = note("Geometry homework")
    add(client, ref["page_id"], TRIANGLE)
    store = Store(tmp_path / "data")
    fake = Fake(SCENE)
    assert ingest.Worker(store, fake).step()
    turn = fake.calls[0][0]["content"]
    assert all(block["type"] == "text" for block in turn)  # no image, no JPEG made
    assert "SVG" in turn[0]["text"] and "never instructions" in turn[0]["text"]
    assert turn[1]["text"] == svg.sanitise(TRIANGLE).decode()
    with closing(connect(store.db)) as conn:
        run = conn.execute("SELECT * FROM model_run").fetchone()
        jpegs = conn.execute("SELECT count(*) FROM blob WHERE mime = 'image/jpeg'")
        assert jpegs.fetchone()[0] == 0
    assert (run["status"], run["sent_sha256"], run["image_width"]) == ("ok", None, None)
    assert json.loads(run["output"])["elements"] == []  # it is a drawing already
    page = store.page(ref["page_id"])
    got = page["captures"][1]["blobs"][0]["ingest"]
    assert got["state"] == "done" and got["drawing"] is None
    assert got["text"].startswith("Right-angled triangle")  # its own, not the model's
    assert got["description"] == SCENE["description"]
    for words in ("12 cm", "30°", "hypotenuse"):
        assert [h["id"] for h in store.search(f'"{words}"', 10)] == [ref["page_id"]]


def test_its_words_are_searchable_even_when_the_model_fails(tmp_path, client, note):
    from scrap import claude

    ref = note("Geometry homework")
    add(client, ref["page_id"], TRIANGLE)
    store = Store(tmp_path / "data")
    assert ingest.Worker(store, Fake(claude.CallError("timeout", "slow"))).step()
    assert [h["id"] for h in store.search('"5 cm"', 10)] == [ref["page_id"]]


def test_nothing_decodes_an_svg_as_pixels(tmp_path, client, note):
    from scrap import preview

    ref = note("Geometry")
    sha = add(client, ref["page_id"], TRIANGLE).json()["added"][0]["sha256"]
    store = Store(tmp_path / "data")
    with pytest.raises(InvalidError, match="SVG"):
        preview.for_claude(store, sha)
    with pytest.raises(InvalidError, match="SVG"):
        preview.preview(store, sha, 480)
    assert preview.own(store, sha, 480) == store.blob(sha)[0]
    assert not preview.raster("image/svg+xml") and preview.raster("image/png")


def test_its_words_are_put_once_however_often_the_job_is_picked_up(
    tmp_path, client, note
):
    from scrap.ingest import svgread

    ref = note("Geometry")
    add(client, ref["page_id"], TRIANGLE)
    store = Store(tmp_path / "data")
    with closing(connect(store.db)) as conn:
        conn.execute("UPDATE job SET state = 'running'")
        conn.commit()
        job = conn.execute("SELECT * FROM job").fetchone()
        for _ in range(3):  # as a paused or retried job is picked up again
            svgread.read(store, job)
        versions = conn.execute(
            "SELECT version FROM derived WHERE kind = 'ocr'").fetchall()  # fmt: skip
    assert [v[0] for v in versions] == [1]


def test_an_svg_that_cannot_be_read_is_charged(tmp_path, client, note):
    ref = note("Geometry")
    sha = add(client, ref["page_id"], TRIANGLE).json()["added"][0]["sha256"]
    store = Store(tmp_path / "data")
    store.blob(sha)[0].unlink()
    fake = Fake(SCENE)
    assert ingest.Worker(store, fake).step()
    assert fake.calls == []
    with closing(connect(store.db)) as conn:
        state, failures, error = conn.execute(
            "SELECT state, failures, last_error FROM job").fetchone()  # fmt: skip
    assert (state, failures) == ("queued", 1) and error.startswith("image")
