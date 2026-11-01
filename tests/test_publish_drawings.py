"""A page's drawings published (#520; docs/reference/public-site.md, "Drawings"): the
PWA's SVG, with Excalidraw's scene in it, cleaned by scrap (the photo in it its
preview, no original bytes or EXIF, private addresses and links gone, a foreign image
dropped), re-embedded, and published as an img-*.svg beside the page, with Open in
Excalidraw and Download links."""

import base64
import hashlib
import io
import re
from urllib.parse import quote, unquote

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from publishhelp import SITE, Site, configure, page
from scrap.app import create_app
from scrap.publish import scene
from scrap.publish.drawings import clean_drawing
from scrap.publish.errors import CheckError
from scrap.store import new_ulid

OWN = "https://scrap.example.org"  # scrap's own address, never published


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


def photo(colour=(200, 30, 30), size=(400, 300)) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    exif[0x0110] = "EOS secret"
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG", exif=exif)
    return out.getvalue()


def data_url(data: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def drawn(elements: list, files: dict, images: list[bytes], words: str = "") -> str:
    """An SVG as Excalidraw's exportToSvg writes one with its scene embedded."""
    sc = {"type": "excalidraw", "version": 2, "source": OWN, "elements": elements,
          "appState": {"viewBackgroundColor": "#ffffff", "gridSize": 20,
                       "theme": "dark", "name": "secret"},
          "files": files, "extra": "dropped"}  # fmt: skip
    symbols = "".join(
        f'<symbol id="image-{fid}"><image href="{data_url(b)}" width="100%"'
        ' height="100%"></image></symbol>'
        for fid, b in zip(files, images, strict=False)
    )
    uses = "".join(f'<use href="#image-{fid}" width="400" height="300"></use>'
                   for fid in files)  # fmt: skip
    meta = scene.metadata(scene.encode(sc))
    return (
        '<svg version="1.1" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"'
        f' width="400" height="300">{meta}<defs>{symbols}'
        '<style class="style-fonts"></style></defs>'
        f'<g>{uses}</g><text x="10" y="20">{words}</text></svg>'
    )


def made(client, original: bytes) -> tuple[dict, str, str]:
    """A public page with a photo and a drawing of it: the page, the drawing's id,
    the photo's sha."""
    sent = [("file", ("b.jpg", original, "image/jpeg"))]
    data = {"id": new_ulid(), "text": "Board"}
    ref = client.post("/api/captures", data=data, files=sent).json()
    p = client.patch(f"/api/pages/{ref['slug']}", json={"public": True}).json()
    cap = p["captures"][0]
    sha = cap["blobs"][0]["sha256"]
    rect = {"id": "r1", "type": "rectangle", "x": 1, "y": 1, "width": 9, "height": 9}
    saved = client.put(
        f"/api/captures/{cap['id']}/photos/{sha}/drawing",
        json={"base_version": None, "scene": {"elements": [rect], "width": 400,
                                               "height": 300}},
    )  # fmt: skip
    assert saved.status_code == 200, saved.text
    return client.get(f"/api/pages/{p['slug']}").json(), str(saved.json()["id"]), sha


def pair(sha: str, key: str, opens: bool = True) -> str:
    """A photo and its drawing, as the publish mode writes them."""
    links = (
        f'<a href="scrap-excalidraw:{key}" target="_blank" rel="noopener noreferrer">'
        f'Open in Excalidraw</a> · <a href="scrap-drawing:{key}" download>Download</a>'
        if opens
        else f'<a href="scrap-drawing:{key}" download>Download</a>'
    )
    return (
        '<div class="pair"><div class="tabs" role="radiogroup" aria-label="Show">'
        '<input type="radio" name="pair-1" id="pair-1-photo" class="tab-input">'
        '<label for="pair-1-photo">Photo</label>'
        '<input type="radio" name="pair-1" id="pair-1-drawing" class="tab-input"'
        ' checked><label for="pair-1-drawing">Drawing</label></div>'
        f'<figure class="orig"><img src="scrap-blob:{sha}" alt="b.jpg"></figure>'
        f'<figure class="drawing"><img src="scrap-drawing:{key}" alt="Drawing">'
        f'</figure></div><p class="drawing-get">{links}</p>'
    )


def publish(client, p: dict, body: str, drawings: list[dict]):
    ask = {"html": page(body, title=p["title"]), "base_rev": p["rev"],
           "confirmed": True, "drawings": drawings}  # fmt: skip
    return client.put(f"/api/pages/{p['slug']}/published", json=ask)


def svg_scene(svg: str) -> dict:
    return scene.decode(scene.payload(svg))


def test_a_drawing_is_published_clean(client, site):
    original = photo()
    p, key, sha = made(client, original)
    foreign = photo((0, 0, 255), (50, 50))  # on no page: dropped
    elements = [
        {"id": "img", "type": "image", "fileId": "orig", "x": 0, "y": 0},
        {"id": "img2", "type": "image", "fileId": "theirs", "x": 0, "y": 0},
        {"id": "t", "type": "text", "text": f"see {OWN}/p/private or /api/pages/x",
         "originalText": "scrap.example.org:8446", "link": f"{OWN}/p/private",
         "customData": {"secret": 1}},
        {"id": "l", "type": "rectangle", "link": "/p/private-page"},
        {"id": "w", "type": "rectangle", "link": "https://example.com/ok"},
        {"id": "gone", "type": "text", "text": "SECRET deleted", "isDeleted": True},
    ]  # fmt: skip
    files = {
        "orig": {"id": "orig", "mimeType": "image/jpeg", "dataURL": data_url(original),
                 "created": 5, "lastRetrieved": 6},
        "theirs": {"id": "theirs", "mimeType": "image/jpeg",
                   "dataURL": data_url(foreign)},
    }  # fmt: skip
    svg = drawn(elements, files, [original, foreign], f"see {OWN}/p/private")
    r = publish(client, p, pair(sha, key), [{"key": key, "svg": svg}])
    assert r.status_code == 200, r.text
    unit = site.folder / "www" / "p" / p["slug"]
    names = sorted(f.name for f in unit.iterdir())
    (svg_name,) = [n for n in names if n.endswith(".svg")]
    assert re.fullmatch(r"img-[12]-[0-9a-f]{10}\.svg", svg_name)
    out = (unit / svg_name).read_bytes()
    text = out.decode()
    # no original bytes, no EXIF, no scrap address, no deleted words, anywhere
    assert base64.b64encode(original)[:200].decode() not in text
    assert "scrap.example.org" not in text and "/api/" not in text
    assert "SECRET" not in text
    got = svg_scene(text)
    assert set(got) == {"type", "version", "source", "elements", "appState", "files"}
    assert got["source"] == "scrap"
    assert got["appState"] == {"viewBackgroundColor": "#ffffff", "gridSize": 20}
    (fid,) = got["files"]
    embedded = base64.b64decode(got["files"][fid]["dataURL"].split(",", 1)[1])
    assert embedded != original and b"EOS secret" not in embedded
    assert not Image.open(io.BytesIO(embedded)).getexif()
    preview = client.get(f"/api/blobs/{sha}/preview?size=2048").content
    assert embedded == preview  # the page's 2048-pixel preview
    assert fid == hashlib.sha1(data_url(preview).encode()).hexdigest()  # noqa: S324
    by_id = {e["id"]: e for e in got["elements"]}
    assert set(by_id) == {"img", "t", "l", "w"}  # theirs and the deleted one gone
    assert by_id["img"]["fileId"] == fid
    assert by_id["t"]["text"] == "see a private link or a private link"
    assert by_id["t"]["originalText"] == "a private link"
    assert by_id["t"]["link"] is None and "customData" not in by_id["t"]
    assert by_id["l"]["link"] is None  # a private page
    assert by_id["w"]["link"] == "https://example.com/ok"
    # what is drawn: the photo's preview only, under the new id; the text scrubbed
    images = re.findall(r'href="data:image/jpeg;base64,([^"]*)"', text)
    assert [base64.b64decode(i) for i in images] == [preview]
    assert f'id="image-{fid}"' in text and f'href="#image-{fid}"' in text
    assert "<text" in text and "see a private link</text>" in text
    # the page: the drawing's img, its download, and Open in Excalidraw
    index = (unit / "index.html").read_text()
    path = f"/p/{p['slug']}/{svg_name}"
    assert f'<img src="{path}" alt="Drawing">' in index
    assert f'<a href="{path}" download>Download</a>' in index
    opens = "https://excalidraw.com/#url=" + quote(f"{SITE}{path}", safe="")
    assert f'<a href="{opens}" target="_blank" rel="noopener noreferrer">' in index
    assert unquote(opens.split("#url=", 1)[1]) == f"{SITE}{path}"
    assert "scrap-drawing" not in index and "scrap-excalidraw" not in index


def test_a_drawing_must_be_the_pages_and_sent(client):
    p, key, sha = made(client, photo())
    svg = drawn([{"id": "r", "type": "rectangle"}], {}, [])
    no = publish(client, p, pair(sha, key), [])
    assert (no.status_code, no.json()["error"]) == (422, "bad_drawing")
    other = publish(client, p, pair(sha, "999"), [{"key": "999", "svg": svg}])
    assert (other.status_code, other.json()["error"]) == (422, "bad_placeholder")
    both = [{"key": key, "svg": svg}, {"key": "998", "svg": svg}]
    extra = publish(client, p, pair(sha, key), both)
    assert (extra.status_code, extra.json()["error"]) == (422, "bad_drawing")
    twice = publish(client, p, pair(sha, key), [{"key": key, "svg": svg}] * 2)
    assert (twice.status_code, twice.json()["error"]) == (422, "bad_request")
    ok = publish(client, p, pair(sha, key, opens=False), [{"key": key, "svg": svg}])
    assert ok.status_code == 200, ok.text


def test_open_in_excalidraw_needs_an_https_site(client, monkeypatch):
    p, key, sha = made(client, photo())
    svg = drawn([{"id": "r", "type": "rectangle"}], {}, [])
    monkeypatch.setenv("SCRAP_PUBLISH_SITE", "http://pages.local")
    r = publish(client, p, pair(sha, key), [{"key": key, "svg": svg}])
    assert (r.status_code, r.json()["error"]) == (422, "bad_placeholder")


def test_a_drawing_counts_toward_the_caps(client, monkeypatch):
    from scrap.publish import files as publish_files

    p, key, sha = made(client, photo())
    svg = drawn([{"id": "r", "type": "rectangle"}], {}, [])
    monkeypatch.setattr(publish_files, "MAX_FILES", 1)  # the photo, then the drawing
    r = publish(client, p, pair(sha, key), [{"key": key, "svg": svg}])
    assert (r.status_code, r.json()["error"]) == (422, "too_many_files")


def no_photos(data: bytes) -> bytes | None:
    return None


def keep(text: str) -> str:
    return text


@pytest.mark.parametrize(
    ("svg", "why"),
    [
        ('<svg xmlns="http://www.w3.org/2000/svg"></svg>', "no single"),
        (drawn([], {}, []).replace("version:2", "version:1"), "no single"),
        (drawn([], {}, []) + "<!-- payload-start -->", "no single"),
        (drawn([], {}, []).replace(
            "<!-- payload-end -->",
            "<!-- payload-end --><!-- payload-type:application/vnd.excalidraw+json -->",
        ), "no single"),  # fmt: skip
        ("<svg><!-- payload-type:application/vnd.excalidraw+json --><!-- payload-vers"
         "ion:2 --><!-- payload-start -->@@@<!-- payload-end --></svg>", "not base64"),
        ("<svg><!-- payload-type:application/vnd.excalidraw+json --><!-- payload-vers"
         "ion:2 --><!-- payload-start -->" + base64.b64encode(b'{"type":"excalidraw"}')
         .decode() + "<!-- payload-end --></svg>", "form"),
        ("<svg><!-- payload-type:application/vnd.excalidraw+json --><!-- payload-vers"
         "ion:2 --><!-- payload-start -->" + base64.b64encode(
             b'{"version":"1","encoding":"bstring","compressed":true,"encoded":"xx"}'
         ).decode() + "<!-- payload-end --></svg>", "cannot be read"),
    ],
)  # fmt: skip
def test_a_malformed_scene_is_refused(svg: str, why: str) -> None:
    with pytest.raises(CheckError) as refused:
        clean_drawing(svg, no_photos, keep, lambda _: None)
    assert refused.value.code == "bad_drawing" and why in refused.value.detail


def test_a_scene_that_is_not_one_is_refused() -> None:
    clean_drawing(drawn([], {}, []), no_photos, keep, lambda _: None)  # a real one
    for bad in ({"type": "other", "elements": []}, {"type": "excalidraw"}):
        mark = scene.metadata(scene.encode(bad))
        text = f'<svg xmlns="http://www.w3.org/2000/svg">{mark}</svg>'
        with pytest.raises(CheckError):
            clean_drawing(text, no_photos, keep, lambda _: None)


def test_a_zip_bomb_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(scene, "MAX_SCENE", 1000)
    big = {"type": "excalidraw", "elements": [{"id": "x" * 5000}]}
    text = f'<svg xmlns="http://www.w3.org/2000/svg">{scene.metadata(scene.encode(big))}</svg>'
    with pytest.raises(CheckError, match="over"):
        clean_drawing(text, no_photos, keep, lambda _: None)


def test_the_payload_reads_as_excalidraw_writes_it() -> None:
    # Excalidraw's own encoding (data/encode.ts): JSON.stringify of the byte string,
    # then btoa; Python's encode must read back, and write the same form
    sc = {"type": "excalidraw", "elements": [{"id": "é", "text": "naïve ✓"}]}
    assert scene.decode(scene.encode(sc)) == sc
    wrapper = base64.b64decode(scene.encode(sc)).decode("latin-1")
    assert wrapper.startswith('{"version":"1","encoding":"bstring","compressed":true')
