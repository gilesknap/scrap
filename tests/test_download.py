import io
import zipfile

from scrap.app import attachment
from scrap.backup import file_name
from scrap.store import new_ulid

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def test_text_page_downloads_as_markdown(client, note):
    ref = note("Shopping list\nmilk and eggs")
    response = client.get(f"/api/pages/{ref['slug']}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="shopping-list.md"')
    text = response.text
    assert text.startswith('---\ntitle: "Shopping list"\n')
    assert text.endswith("---\n\nShopping list\nmilk and eggs\n\n")


def test_page_with_files_downloads_as_a_zip_with_relative_links(client):
    files = [
        ("file", ("board.png", PNG, "image/png")),
        ("file", ("BOARD.png", PNG + b"2", "image/png")),  # same name to a phone
        ("file", ("../../etc/notes.txt", b"hello", "text/plain")),
    ]
    data = {"id": new_ulid(), "text": "Whiteboard"}
    ref = client.post("/api/captures", data=data, files=files).json()
    response = client.get(f"/api/pages/{ref['page_id']}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'filename="whiteboard.zip"' in response.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(response.content))
    assert zf.namelist() == [
        "whiteboard.md",
        "files/board.png",
        "files/BOARD-2.png",
        "files/notes.txt",
    ]
    assert zf.read("files/BOARD-2.png") == PNG + b"2"
    md = zf.read("whiteboard.md").decode()
    # The text's images, once each, at the files here; then the file it doesn't show
    assert md.endswith(
        "---\n\nWhiteboard\n\n![board.png](files/board.png)\n\n"
        "![BOARD.png](files/BOARD-2.png)\n\n[../../etc/notes.txt](files/notes.txt)\n"
    )
    assert "/api/blobs" not in md


def test_download_points_edited_and_foreign_embeds_right(client):
    other = client.post(
        "/api/captures",
        data={"id": new_ulid()},
        files=[("file", ("far.png", PNG + b"far", "image/png"))],
    ).json()
    far = client.get(f"/api/pages/{other['page_id']}").json()["captures"][0]
    far_sha = far["blobs"][0]["sha256"]
    ref = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "Mine"},
        files=[("file", ("near.png", PNG, "image/png"))],
    ).json()
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    near = page["captures"][0]["blobs"][0]["sha256"]
    body = (
        f"Mine\n\nSee ![my alt](/api/blobs/{near}) and [link](/api/blobs/{near})"
        f"\n\n![](/api/blobs/{far_sha}/preview?size=2048)"
    )
    url = f"/api/pages/{ref['page_id']}"
    client.patch(url, json={"base_rev": 1, "body": body})
    zf = zipfile.ZipFile(io.BytesIO(client.get(f"{url}/download").content))
    md = zf.read("mine.md").decode()
    assert "See ![my alt](files/near.png) and [link](files/near.png)" in md
    assert f"![](/api/blobs/{far_sha}/preview?size=2048)" in md  # another page's
    assert md.count("files/near.png") == 2  # shown in the text: not again below


def test_download_of_a_missing_or_trashed_page_is_404(client, note):
    assert client.get("/api/pages/nope/download").status_code == 404
    ref = note()
    client.delete(f"/api/pages/{ref['slug']}")
    assert client.get(f"/api/pages/{ref['slug']}/download").status_code == 404


def test_blob_download_names_the_original(client):
    files = [("file", ("Café photo.png", PNG, "image/png"))]
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
    sha = client.get(f"/api/pages/{ref['slug']}").json()["captures"][0]["blobs"][0][
        "sha256"
    ]
    assert "content-disposition" not in client.get(f"/api/blobs/{sha}").headers
    response = client.get(f"/api/blobs/{sha}?download=1")
    assert response.content == PNG
    assert response.headers["content-disposition"] == (
        'attachment; filename="Caf_ photo.png"; '
        "filename*=UTF-8''Caf%C3%A9%20photo.png"
    )


def test_safe_names():
    sha = "ab" * 32
    assert file_name(None, sha, "image/png") == "abababababab.png"
    assert file_name("..", sha, "image/png") == "abababababab.png"
    long = file_name("x" * 300 + ".jpeg", sha, "image/jpeg")
    assert len(long) == 120 and long.endswith("x.jpeg")  # its type kept
    assert file_name("C:\\Users\\me\\a b.jpg", sha, "image/jpeg") == "a b.jpg"
    assert file_name('x"y\n<z>.txt', sha, "text/plain") == "x_y_z_.txt"
    assert attachment('a"\\b.md') == (
        "attachment; filename=\"a__b.md\"; filename*=UTF-8''a%22%5Cb.md"
    )


def test_download_leaves_code_alone_and_shows_each_photo_once(client):
    files = [
        ("file", ("a.png", PNG, "image/png")),
        ("file", ("a again.png", PNG, "image/png")),  # the same photo: one copy
        ("file", ("b.png", PNG + b"b", "image/png")),
        ("file", ("c.png", PNG + b"c", "image/png")),
    ]
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
    url = f"/api/pages/{ref['page_id']}"
    blobs = client.get(url).json()["captures"][0]["blobs"]
    a, _, b, c = (x["sha256"] for x in blobs)
    body = (
        f"`![](/api/blobs/{a})` and [only a link](/api/blobs/{b})\n\n"
        f"```\n![](/api/blobs/{c})\n```\n\n[get it](/api/blobs/{c}?download=1)"
    )
    client.patch(url, json={"base_rev": 1, "body": body})
    zf = zipfile.ZipFile(io.BytesIO(client.get(f"{url}/download").content))
    assert zf.namelist()[1:] == ["files/a.png", "files/b.png", "files/c.png"]
    md = zf.read(zf.namelist()[0]).decode()
    assert f"`![](/api/blobs/{a})`" in md and f"```\n![](/api/blobs/{c})\n```" in md
    assert "[only a link](files/b.png)" in md and "[get it](files/c.png)" in md
    # none is shown as an image in the text: each is, once, below it
    for f in ("a", "b", "c"):
        assert md.count(f"![{f}.png](files/{f}.png)") == 1
    assert "a again" not in md
