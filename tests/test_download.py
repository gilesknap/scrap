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
        ("file", ("board.png", PNG + b"2", "image/png")),  # same name, other bytes
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
        "files/board-2.png",
        "files/notes.txt",
    ]
    assert zf.read("files/board-2.png") == PNG + b"2"
    md = zf.read("whiteboard.md").decode()
    assert "![board.png](files/board.png)\n![board.png](files/board-2.png)\n" in md
    assert "[../../etc/notes.txt](files/notes.txt)" in md


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
    assert file_name("C:\\Users\\me\\a b.jpg", sha, "image/jpeg") == "a b.jpg"
    assert file_name('x"y\n<z>.txt', sha, "text/plain") == "x_y_z_.txt"
    assert attachment('a"\\b.md') == (
        "attachment; filename=\"a__b.md\"; filename*=UTF-8''a%22%5Cb.md"
    )
