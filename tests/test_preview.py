import io

import pytest
from PIL import Image

from scrap import backup, preview
from scrap.store import Store, new_ulid


def image(fmt: str, size=(300, 100), exif_orientation: int | None = None) -> bytes:
    im = Image.new("RGB", size, "red")
    im.paste("blue", (0, 0, size[0] // 2, size[1]))  # left half blue
    out = io.BytesIO()
    exif = Image.Exif()
    if exif_orientation:
        exif[0x0112] = exif_orientation
    im.save(out, fmt, exif=exif)
    return out.getvalue()


@pytest.fixture
def upload(client):
    """Capture one file; return its SHA-256."""

    def send(data: bytes, name="p.jpg", mime="image/jpeg") -> str:
        files = [("file", (name, data, mime))]
        ref = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
        page = client.get(f"/api/pages/{ref['slug']}").json()
        return page["captures"][0]["blobs"][0]["sha256"]

    return send


def get_preview(client, sha, size=2048):
    response = client.get(f"/api/blobs/{sha}/preview?size={size}")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    assert "immutable" in response.headers["cache-control"]
    return Image.open(io.BytesIO(response.content))


def test_preview_downscales_and_keeps_small_ones(client, upload):
    sha = upload(image("JPEG", (3000, 1000)))
    assert get_preview(client, sha).size == (2048, 683)
    assert get_preview(client, sha, 480).size == (480, 160)
    assert get_preview(client, upload(image("PNG"), "p.png", "image/png")).size == (
        300,
        100,
    )


def test_preview_turns_the_photo_upright(client, upload):
    sha = upload(image("JPEG", exif_orientation=6))  # camera held on its side
    im = get_preview(client, sha)
    assert im.size == (100, 300)
    assert not im.getexif()  # no EXIF (nor GPS) in previews
    # rotated 90 clockwise: the blue left half is now the top
    top, bottom = im.getpixel((50, 5)), im.getpixel((50, 295))
    assert isinstance(top, tuple) and isinstance(bottom, tuple)
    assert top[2] > 200 and bottom[0] > 200


def test_heic_preview(client, upload):
    sha = upload(image("HEIF"), "IMG_0001.HEIC", "image/heic")
    assert get_preview(client, sha, 480).size == (300, 100)


def test_preview_is_made_once_and_cached(client, upload, monkeypatch, tmp_path):
    sha = upload(image("JPEG"))
    get_preview(client, sha)
    made = []
    monkeypatch.setattr(preview, "_make", lambda *a: made.append(a))
    get_preview(client, sha)
    assert made == []
    cached = tmp_path / "data/cache/previews/2048" / sha[:2] / f"{sha}.jpg"
    assert cached.is_file()
    # the cache is not part of a backup
    backup.backup(Store(tmp_path / "data"), tmp_path / "bak")
    assert not (tmp_path / "bak/cache").exists()


@pytest.mark.parametrize(
    "path, status",
    [
        ("/api/blobs/../scrap.db/preview", 404),
        (f"/api/blobs/{'0' * 64}/preview", 404),
        ("/api/blobs/%2e%2e%2fscrap.db/preview", 404),
    ],
)
def test_preview_of_nothing_is_404(client, path, status):
    assert client.get(path).status_code == status


def test_previews_refused(client, upload, monkeypatch):
    sha = upload(image("JPEG"))
    assert client.get(f"/api/blobs/{sha}/preview?size=999").status_code == 422
    text = upload(b"hello", "a.txt", "text/plain")
    assert client.get(f"/api/blobs/{text}/preview").status_code == 422
    broken = upload(b"\x89PNG\r\n\x1a\n" + b"\0" * 32, "b.png", "image/png")
    assert client.get(f"/api/blobs/{broken}/preview").status_code == 422
    big = upload(image("PNG", (200, 200)), "big.png", "image/png")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10_000)  # Pillow's bomb error
    assert client.get(f"/api/blobs/{big}/preview").status_code == 422
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)  # ours, before decoding
    monkeypatch.setattr(preview, "MAX_PIXELS", 30_000)
    response = client.get(f"/api/blobs/{big}/preview?size=480")
    assert response.status_code == 422
    assert response.json()["detail"] == "image too large to preview"
