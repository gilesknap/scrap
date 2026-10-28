"""A single page's download carries what the page shows (#405): tags, status and
topics, Claude's notes under one marked heading, what links here, a file's text, and
full addresses for [[slug]] links when the address is set. `scrap export` carries none
of the notes."""

import io
import zipfile
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from scrap import backup
from scrap.app import create_app
from scrap.page_notes import MAX_FILE_TEXT, NOTES_HEADING
from scrap.store import Store, connect, new_ulid, now, topics, writeups

NOTES = "Claude's notes (written by a model, may be wrong)"


@pytest.fixture
def data(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def client(data):
    return TestClient(create_app(data))


def add(client, text, **extra):
    r = client.post("/api/captures", json={"id": new_ulid(), "text": text, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def sql(data, query, *args):
    with closing(connect(data / "scrap.db")) as conn:
        conn.execute(query, args)
        conn.commit()


def md(client, ref, query=""):
    return client.get(f"/api/pages/{ref['page_id']}/download{query}").text


@pytest.fixture
def cast(client, data):
    """Pages: a (tagged, in a topic, with Claude's notes), b (related to a), l (links
    to a), and topic t (a's), with a synthesis."""
    a = add(client, "Alpha\nthe body", tags=["epics"])
    b = add(client, "Beta page")
    link = add(client, f"Linker\nsee [[{a['slug']}]]")
    stamp = now()
    sql(
        data,
        "INSERT INTO enrichment (page_id, producer, summary, updated_at)"
        " VALUES (?, 'm', 'A short Claude summary.', ?)",
        a["page_id"],
        stamp,
    )
    sql(data, "INSERT INTO model_tag VALUES (?, 'epics', 'on', 'm', ?)",
        a["page_id"], stamp)  # fmt: skip
    sql(data, "INSERT INTO related VALUES (?, ?, 1)", a["page_id"], b["page_id"])
    with closing(connect(data / "scrap.db")) as conn:
        t = topics.create(conn, "Epics", "epics", "epics-topic", "m", stamp)
        assert t
        topics.add_sources(conn, t, [a["page_id"]], "m", stamp)
        writeups.put(
            conn, t, stamp, producer="m", run_id=None, prompt_version="1",
            summary="Topic lead", text=f"All about [[{a['slug']}]].", guidance=None,
        )  # fmt: skip
        conn.commit()
    return a, b, link, t


def test_front_matter_has_tags_status_and_topics(client, cast):
    a, b, *_ = cast
    text = md(client, a)
    head = text.split("\n---\n")[0]
    assert 'tags: ["epics"]' in head and 'topics: ["epics-topic"]' in head
    todo = add(client, "Do it", kind="todo")
    assert '\nstatus: "open"\n' in md(client, todo)
    assert "\nstatus:" not in md(client, b)


def test_claudes_notes_are_one_marked_section(client, cast):
    a, b, *_ = cast
    text = md(client, a)
    assert f"\n## {NOTES}\n" in text and NOTES_HEADING in text
    notes = text.split(NOTES_HEADING)[1]
    assert "**Summary**\n\nA short Claude summary." in notes
    assert "**Tags Claude added:** epics" in notes
    assert f"**Related pages**\n\n- [[{b['slug']}]] Beta page" in notes
    assert text.index("the body") < text.index(NOTES_HEADING)  # after the owner's text
    assert "the body" not in notes


def test_a_topic_page_has_its_synthesis_in_the_notes(client, cast):
    *_, t = cast
    text = client.get(f"/api/pages/{t}/download").text
    assert "**Topic synthesis**\n\nAll about [[" in text
    assert "**Summary**\n\nTopic lead" in text


def test_notes_off_leaves_only_claudes_part_out(client, cast):
    a, _, link, _ = cast
    text = md(client, a, "?notes=0")
    assert "Claude" not in text and "A short" not in text
    assert f"## Linked from\n\n- [[{link['slug']}]] Linker" in text
    assert 'tags: ["epics"]' in text


def test_a_page_with_nothing_to_add_has_no_empty_headings(client):
    ref = add(client, "Plain\nbody")
    text = md(client, ref)
    assert "Claude" not in text and "Linked from" not in text
    assert text.endswith("---\n\nPlain\nbody\n\n")


def test_slug_links_are_full_addresses_only_when_set(client, cast, monkeypatch):
    a, _, link, _ = cast
    slug = a["slug"]
    assert f"see [[{slug}]]" in md(client, link)
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://scrap.example:8446/")
    text = md(client, link)
    assert f"see [{slug}](https://scrap.example:8446/p/{slug})" in text
    assert "[[" not in text
    notes = client.get(f"/api/pages/{cast[3]}/download").text
    assert f"[{slug}](https://scrap.example:8446/p/{slug})" in notes
    fenced = add(client, f"```\n[[{slug}]]\n```\n`[[{slug}]]` ![[{slug}]]")
    assert md(client, fenced).count(f"[[{slug}]]") == 3  # code and an embed: as typed


def test_export_leaves_the_notes_and_the_rest_out(client, cast, data, tmp_path):
    out = tmp_path / "md"
    assert backup.export(Store(data), out)
    for file in out.glob("*.md"):
        text = file.read_text()
        assert "Claude's notes" not in text and "Linked from" not in text
        assert "\ntags:" not in text and "\ntopics:" not in text


def test_a_files_text_is_fenced_and_capped(client, data):
    files = [
        ("file", ("n.txt", b"x", "text/plain")),
        ("file", ("e.txt", b"y", "text/plain")),
    ]
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
    cap = client.get(f"/api/pages/{ref['page_id']}").json()["captures"][0]
    n, _ = (b["sha256"] for b in cap["blobs"])
    long = "word " * (MAX_FILE_TEXT // 5 + 50)
    sql(data, "INSERT INTO derived (capture_id, source_sha256, kind, version, producer,"
        " text, created_at) VALUES (?, ?, 'ocr', 1, 'scrap', ?, ?)",
        cap["id"], n, "```\n" + long, now())  # fmt: skip
    zf = zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/pages/{ref['page_id']}/download").content)
    )
    text = zf.read(zf.namelist()[0]).decode()
    assert "[n.txt](files/n.txt)\n\n````text\n```\nword word" in text
    assert text.count("word") <= MAX_FILE_TEXT // 5 + 1
    assert "[text cut here]\n````\n" in text
    assert (
        "[e.txt](files/e.txt)\n" in text and text.count("````text") == 1
    )  # none: none


def photo(exif: bool) -> bytes:
    im = Image.new("RGB", (64, 48), "red")
    out = io.BytesIO()
    if exif:
        e = Image.Exif()
        e[0x010F] = "MakerName"
        e.get_ifd(0x8825)[1] = "N"  # a GPS IFD
        im.save(out, "JPEG", exif=e)
    else:
        im.save(out, "JPEG")
    return out.getvalue()


def test_photos_as_previews_carry_no_exif_or_gps(client):
    original = photo(exif=True)
    assert b"MakerName" in original
    files = [("file", ("IMG.JPG", original, "image/jpeg")),
             ("file", ("bad.png", b"\x89PNG not a picture", "image/png"))]  # fmt: skip
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
    url = f"/api/pages/{ref['page_id']}/download"
    kept = zipfile.ZipFile(io.BytesIO(client.get(url).content))
    assert kept.read("files/IMG.JPG") == original  # Download keeps the originals
    shared = zipfile.ZipFile(io.BytesIO(client.get(url + "?photos=preview").content))
    assert shared.namelist()[1:] == [
        "files/IMG.jpg"
    ]  # the one it cannot decode: left out
    jpeg = shared.read("files/IMG.jpg")
    assert b"MakerName" not in jpeg and b"Exif" not in jpeg
    assert Image.open(io.BytesIO(jpeg)).getexif().get_ifd(0x8825) == {}
    assert "(files/IMG.jpg)" in shared.read(shared.namelist()[0]).decode()


def test_a_busy_decoder_is_a_503_to_retry(client, monkeypatch):
    from scrap import backup as module
    from scrap.preview import BusyError

    ref = client.post("/api/captures", data={"id": new_ulid()},
                      files=[("file", ("a.jpg", photo(False), "image/jpeg"))]).json()  # fmt: skip

    def busy(*args):
        raise BusyError()

    monkeypatch.setattr(module, "preview", busy)
    r = client.get(f"/api/pages/{ref['page_id']}/download?photos=preview")
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
