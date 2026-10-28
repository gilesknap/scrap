# pyright: reportOptionalSubscript=false
"""A capture's text placing its own uploads with tokens (#403): ⟦image N⟧ and
⟦file N⟧ (⟦file N: name⟧ too), N the upload's place among the request's files from 1,
become that upload's embed or link where they stand; uploads with no token are added as
before (an image's embed at the end, a file listed below the text)."""

from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from scrap import ingest
from scrap.app import create_app
from scrap.store import Store, connect, new_ulid
from test_files import NoCall, pdf
from test_photos import jpeg


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "data")


@pytest.fixture
def client(app):
    return TestClient(app)


def post(client, text, *parts: tuple[str, bytes, str], **extra):
    data = {"id": new_ulid(), **({"text": text} if text is not None else {}), **extra}
    files = [("file", part) for part in parts]
    r = client.post("/api/captures", data=data, files=files)
    assert r.status_code == 201, r.text
    return client.get(f"/api/pages/{r.json()['page_id']}").json()


def shas(page):
    """The page's files by name."""
    return {b["filename"]: b["sha256"] for c in page["captures"] for b in c["blobs"]}


def image(sha):
    return f"![](/api/blobs/{sha}/preview?size=2048)"


PHOTO = ("a.jpg", jpeg(), "image/jpeg")
PHOTO2 = ("b.jpg", jpeg("blue"), "image/jpeg")
PDF = ("minutes.pdf", pdf("the zanzibar clause"), "application/pdf")
TXT = ("list.txt", b"eggs\nmilk", "text/plain")
MD = ("reading.md", b"# Reading\nthe wombat", "")  # untyped: typed by its name


def test_tokens_become_embeds_and_links_where_they_stand(client):
    text = (
        "Trip\n\n⟦file 2: minutes.pdf⟧\n\nthe view\n\n⟦image 1⟧\n⟦image 3⟧\n\n⟦file 4⟧"
    )
    page = post(client, text, PHOTO, PDF, PHOTO2, MD)
    s = shas(page)
    assert page["body"] == (
        f"Trip\n\n[minutes.pdf](/api/blobs/{s['minutes.pdf']})\n\nthe view\n\n"
        f"{image(s['a.jpg'])}\n{image(s['b.jpg'])}\n\n"
        f"[reading.md](/api/blobs/{s['reading.md']})"
    )
    assert page["title"] == "Trip"
    capture = page["captures"][0]
    assert capture["kind"] == "photo" and capture["text"] == page["body"]
    # stored images first, each group in the order sent, as before
    assert [b["filename"] for b in capture["blobs"]] == [
        "a.jpg", "b.jpg", "minutes.pdf", "reading.md",
    ]  # fmt: skip


@pytest.mark.parametrize("part", [PDF, TXT, MD])
def test_a_file_alone_is_linked_in_place(client, part):
    page = post(client, "Before\n\n⟦file 1: x⟧\n\nafter", part)
    sha = shas(page)[part[0]]
    assert page["body"] == f"Before\n\n[{part[0]}](/api/blobs/{sha})\n\nafter"
    assert page["captures"][0]["kind"] == "file"


def test_the_word_is_a_hint_the_stored_type_decides(client):
    page = post(client, "⟦file 1⟧ ⟦image 2⟧", PHOTO, PDF)
    s = shas(page)
    assert (
        page["body"]
        == f"{image(s['a.jpg'])} [minutes.pdf](/api/blobs/{s['minutes.pdf']})"
    )


def test_uploads_with_no_token_are_added_as_before(client):
    """An untokened image goes to the end; an untokened file is listed below only."""
    page = post(client, "Mixed ⟦image 2⟧", PHOTO, PHOTO2, PDF)
    s = shas(page)
    assert page["body"] == f"Mixed {image(s['b.jpg'])}\n\n{image(s['a.jpg'])}"
    assert "minutes.pdf" not in page["body"]


def test_an_old_client_without_tokens_is_unchanged(client):
    page = post(client, "Caption", PHOTO, PDF, PHOTO2)
    s = shas(page)
    assert page["body"] == f"Caption\n\n{image(s['a.jpg'])}\n\n{image(s['b.jpg'])}"
    assert page["captures"][0]["text"] == "Caption"


def test_a_token_for_no_upload_stays_as_typed(client):
    page = post(client, "Only ⟦image 2⟧ and ⟦file 0⟧ ⟦image 1⟧", PHOTO)
    sha = shas(page)["a.jpg"]
    assert page["body"] == f"Only ⟦image 2⟧ and ⟦file 0⟧ {image(sha)}"
    # with no uploads at all, nothing is a token: a note keeps its brackets
    note = client.post(
        "/api/captures", json={"id": new_ulid(), "text": "⟦image 1⟧ stays"}
    ).json()
    got = client.get(f"/api/pages/{note['page_id']}").json()
    assert (got["title"], got["body"]) == ("⟦image 1⟧ stays", "⟦image 1⟧ stays")


def test_a_token_twice_embeds_twice(client):
    page = post(client, "⟦image 1⟧\n\nagain\n\n⟦image 1⟧", PHOTO)
    sha = shas(page)["a.jpg"]
    assert page["body"] == f"{image(sha)}\n\nagain\n\n{image(sha)}"


def test_a_names_brackets_are_left_out_of_its_link(client):
    page = post(client, "⟦file 1⟧", ("a [draft]  v2.pdf", pdf("x"), "application/pdf"))
    sha = next(iter(shas(page).values()))
    assert page["body"] == f"[a draft v2.pdf](/api/blobs/{sha})"


def test_text_of_tokens_alone_is_titled_as_no_text(client):
    """No words of its own: titled by the time, and its capture has no text, so ingest
    may title it from the photo, as a photo with no caption."""
    page = post(
        client, "⟦image 1⟧\n\n⟦file 2⟧", PHOTO, PDF, created_at="2026-10-28T09:05:00Z"
    )
    assert page["title"] == "2026-10-28 09:05"
    assert page["captures"][0]["text"] is None
    s = shas(page)
    assert (
        page["body"]
        == f"{image(s['a.jpg'])}\n\n[minutes.pdf](/api/blobs/{s['minutes.pdf']})"
    )


def test_a_title_skips_a_leading_token(client):
    page = post(client, "⟦image 1⟧\n# Garden plan\nmore", PHOTO)
    assert page["title"] == "Garden plan"


def test_a_kind_and_due_with_files(client):
    """The composer may now choose a kind with files: a todo with a due date."""
    page = post(client, "Pay the invoice ⟦file 1⟧", PDF, kind="todo", due="2026-11-01")
    assert (page["kind"], page["kind_fixed"], page["due"]) == (
        "todo",
        True,
        "2026-11-01",
    )


def test_a_linked_files_text_is_still_searched_and_counted(client, tmp_path):
    page = post(client, "Contract ⟦file 1⟧", PDF)
    store = Store(tmp_path / "data")
    assert ingest.Worker(store, NoCall()).step()
    hits = store.search("zanzibar", 10)
    assert [h["id"] for h in hits] == [page["id"]]
    # the same file in two pages is a duplicate, as before
    post(client, "Copy ⟦file 1⟧", PDF)
    assert len(store.search("is:duplicate", 10)) == 2
    # deleting its link from the text later: removed, as an image's embed (#303)
    edited = client.patch(
        f"/api/pages/{page['id']}", json={"base_rev": 1, "body": "Contract"}
    ).json()
    assert edited["removed"] == [shas(page)["minutes.pdf"]]
    with closing(connect(store.db)) as conn:  # the file is still the capture's (gc)
        assert conn.execute("SELECT count(*) FROM capture_blob").fetchone()[0] == 2
