import io
import subprocess
import sys
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor

import anyio
import httpx2
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageCms

from scrap import backup, preview
from scrap.app import create_app
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
    monkeypatch.setattr(preview, "DECODE_BUDGET", 100_000)
    response = client.get(f"/api/blobs/{big}/preview?size=480")
    assert response.status_code == 422
    assert response.json()["detail"] == "image too large to preview"


def png_header(width: int, height: int) -> bytes:
    """A PNG that only declares its size: opening it reads no pixels."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return len(data).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")

    head = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", head)
        + chunk(b"IDAT", zlib.compress(b"\0" * 100))
        + chunk(b"IEND", b"")
    )


@pytest.mark.timing  # run alone: see conftest.py
def test_a_photo_too_big_to_decode_is_refused_before_decoding(client, upload):
    sha = upload(png_header(10_000, 10_000), "huge.png", "image/png")  # 100 MP
    start = time.monotonic()
    response = client.get(f"/api/blobs/{sha}/preview?size=480")
    assert response.status_code == 422
    assert response.json()["detail"] == "image too large to preview"
    assert time.monotonic() - start < 3  # refused unread: decoding 100 MP is far slower


PEAK = """
import resource, sys
from pathlib import Path
from scrap import preview
base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
preview._make(Path(sys.argv[1]), Path(sys.argv[2]), 2048)
unit = 2**20 if sys.platform == "darwin" else 2**10  # ru_maxrss: bytes, else KiB
print((resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - base) * unit // 2**20)
"""


def test_a_40_mp_jpeg_decodes_in_little_memory(tmp_path):
    src = tmp_path / "big.jpg"
    make = "from PIL import Image; import sys; Image.new('RGB', (7300, 5500), 'red')"
    subprocess.run(
        [sys.executable, "-c", f"{make}.save(sys.argv[1])", str(src)], check=True
    )
    out = subprocess.run(
        [sys.executable, "-c", PEAK, str(src), str(tmp_path / "out.jpg")],
        check=True,
        capture_output=True,
        text=True,
    )
    assert int(out.stdout) < 150  # MB over the process's own; decoded whole: 160+


def test_one_decode_at_a_time(client, upload, monkeypatch, tmp_path):
    shas = [upload(image("JPEG", (10 + n, 10))) for n in range(4)]
    busy, most = 0, 0
    lock = threading.Lock()

    def slow(src, dest, size):
        nonlocal busy, most
        with lock:
            busy += 1
            most = max(most, busy)
        time.sleep(0.05)
        with lock:
            busy -= 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"jpeg")

    monkeypatch.setattr(preview, "_make", slow)
    store = Store(tmp_path / "data")
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda sha: preview.preview(store, sha, 480), shas))
    assert most == 1


def test_waiting_for_the_decoder_holds_no_worker_thread(tmp_path, monkeypatch):
    app = create_app(tmp_path / "data")
    sync = TestClient(app)
    shas = []
    for n in range(10):
        files = [("file", ("p.jpg", image("JPEG", (10 + n, 10)), "image/jpeg"))]
        ref = sync.post("/api/captures", data={"id": new_ulid()}, files=files).json()
        page = sync.get(f"/api/pages/{ref['slug']}").json()
        shas.append(page["captures"][0]["blobs"][0]["sha256"])
    go = threading.Event()
    decoding = threading.Event()

    def slow(src, dest, size):
        decoding.set()
        go.wait(10)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"jpeg")

    monkeypatch.setattr(preview, "_make", slow)
    codes: list[int] = []

    async def main():
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as c:

            async def get(sha):
                codes.append((await c.get(f"/api/blobs/{sha}/preview")).status_code)

            busy = -1
            async with anyio.create_task_group() as tg:
                for sha in shas:
                    tg.start_soon(get, sha)
                limiter = anyio.to_thread.current_default_thread_limiter()
                # Wait for the state, not a fixed time: one decoding, and the nine
                # others past their threaded steps and waiting. A regression (waiters
                # holding threads) never settles, so it fails at the deadline.
                with anyio.fail_after(30):
                    while not decoding.is_set() or limiter.borrowed_tokens != 1:
                        await anyio.sleep(0.01)
                await anyio.sleep(0.1)  # and it stays settled
                busy = limiter.borrowed_tokens
                assert (await c.get("/healthz")).status_code == 200  # still answered
                go.set()
        return busy

    busy = anyio.run(main)
    assert codes == [200] * 10
    assert (
        busy == 1
    )  # worker threads in use: the one decoding; the nine waiting hold none


def test_a_long_wait_for_the_decoder_is_a_503(client, upload, monkeypatch):
    sha = upload(image("JPEG"))
    monkeypatch.setattr(preview, "WAIT", 0.05)
    with preview._decoder:  # another decode is running
        response = client.get(f"/api/blobs/{sha}/preview")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert client.get(f"/api/blobs/{sha}/preview").status_code == 200


def test_the_colour_profile_is_kept(client, upload):
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    out = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(out, "JPEG", icc_profile=srgb)
    assert get_preview(client, upload(out.getvalue())).info["icc_profile"] == srgb
    cmyk = io.BytesIO()  # a profile for another colour space is dropped
    Image.new("CMYK", (40, 30)).save(cmyk, "JPEG", icc_profile=srgb)
    assert "icc_profile" not in get_preview(client, upload(cmyk.getvalue())).info
