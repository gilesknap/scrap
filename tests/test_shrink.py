import hashlib
import os
import time
from io import BytesIO

import pytest
from PIL import Image

from scrap import shrink
from scrap.__main__ import main
from scrap.store import Store, new_ulid

DAY = 24 * 3600


def jpeg(size=(3200, 2400), orientation=None, quality=100) -> bytes:
    """A big JPEG: red left half, blue right half, with a gradient so it is not tiny."""
    w, h = size
    green = Image.frombytes("L", (w // 10, h // 10), os.urandom(w // 10 * (h // 10)))
    green = green.resize(size, Image.Resampling.BICUBIC)
    left = Image.new("L", size, 0)
    left.paste(255, (0, 0, w // 2, h))
    right = Image.new("L", size, 0)
    right.paste(255, (w // 2, 0, w, h))
    im = Image.merge("RGB", (left, green, right))
    out = BytesIO()
    extra = {}
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        extra["exif"] = exif
    im.save(out, "JPEG", quality=quality, **extra)
    return out.getvalue()


def dims(path):
    with Image.open(path) as im:
        return im.size


def age(store: Store):
    for path in store.files.rglob("*"):
        if path.is_file():
            t = time.time() - 2 * DAY
            os.utime(path, (t, t))


def photo(client, data: bytes, text="A photo", name="p.jpg", mime="image/jpeg"):
    r = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": text},
        files=[("file", (name, data, mime))],
    )
    assert r.status_code == 201, r.text
    return r.json(), hashlib.sha256(data).hexdigest()


@pytest.fixture
def store(client, tmp_path):
    return Store(tmp_path / "data")


def state(store: Store):
    with store.connect() as conn:
        rows = {
            t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
            for t in ("page", "page_rev", "capture_blob", "blob", "derived", "job")
        }
    files = sorted(p.name for p in store.files.rglob("*") if p.is_file())
    return rows, files


def add_derived(store: Store, cid: str, sha: str):
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO derived (capture_id, source_sha256, kind, version, producer,"
            " text, created_at) VALUES (?, ?, 'ocr', 1, 'human', 'words', ?)",
            (cid, sha, "2026-01-01T00:00:00.000Z"),
        )


def test_shrinks_and_repoints_everything(client, store):
    data = jpeg()
    cap, old = photo(client, data, name="IMG_1.jpg")
    page = cap["page_id"]
    age(store)
    with store.connect() as conn:
        cid = conn.execute("SELECT capture_id FROM capture_blob").fetchone()[0]
    add_derived(store, cid, old)
    assert f"/api/blobs/{old}" in client.get(f"/api/pages/{page}").json()["body"]

    report = shrink.run(store, apply=True)

    assert len(report.items) == 1 and report.removed == 1 and report.kept == 0
    with store.connect() as conn:
        (new,) = conn.execute("SELECT sha256 FROM capture_blob").fetchone()
        assert new != old
        assert conn.execute("SELECT count(*) FROM blob").fetchone()[0] == 1
        mime, size = conn.execute("SELECT mime, size FROM blob").fetchone()
        assert (mime, size) == ("image/jpeg", store.blob_path(new).stat().st_size)
        assert size < len(data) / 2
        assert conn.execute("SELECT source_sha256 FROM derived").fetchone()[0] == new
        body = conn.execute("SELECT body FROM page").fetchone()[0]
        assert new in body and old not in body
        assert (
            conn.execute("SELECT author FROM page_rev ORDER BY rev DESC").fetchone()[0]
            == "scrap shrink"
        )
        # the immutability trigger is back
        with pytest.raises(Exception, match="immutable"):
            conn.execute("UPDATE derived SET source_sha256 = 'x'")
        # and the page is found by its words in the index still
        assert conn.execute("SELECT count(*) FROM chunk").fetchone()[0] >= 1
    assert not store.blob_path(old).exists()
    assert store.blob_path(new).is_file()
    assert max(dims(store.blob_path(new))) == shrink.MAX_EDGE
    assert client.get(f"/api/blobs/{new}").status_code == 200

    again = shrink.run(store, apply=True)  # idempotent
    assert again.items == [] and again.small == 1
    assert "would shrink 0" in shrink.run(store).text()


def test_dry_run_changes_nothing(client, store, capsys, tmp_path):
    photo(client, jpeg())
    age(store)
    before = state(store)
    report = shrink.run(store)
    assert len(report.items) == 1 and report.saved > 0
    assert state(store) == before
    main(["shrink", "--data-dir", str(tmp_path / "data")])
    out = capsys.readouterr().out
    assert "would shrink 1 photos over 2560 px" in out
    assert "dry run: --apply shrinks them; back up first" in out
    assert state(store) == before
    main(["shrink", "--apply", "--data-dir", str(tmp_path / "data")])
    assert "shrank 1 photos" in capsys.readouterr().out
    assert state(store) != before


def test_a_file_still_used_elsewhere_is_kept(client, store):
    cap, old = photo(client, jpeg())
    age(store)
    with store.connect() as conn:
        cid = conn.execute("SELECT capture_id FROM capture_blob").fetchone()[0]
        conn.execute(  # a model run that sent this very file
            "INSERT INTO model_run (capture_id, source_sha256, purpose, model,"
            " prompt_version, sent_sha256, request, started_at)"
            " VALUES (?, ?, 'ingest', 'm', 'v', ?, '{}', '2026-01-01T00:00:00.000Z')",
            (cid, old, old),
        )
    report = shrink.run(store, apply=True)
    assert report.removed == 0 and report.kept == 1
    assert store.blob_path(old).is_file()
    with store.connect() as conn:
        assert conn.execute("SELECT sha256 FROM capture_blob").fetchone()[0] != old
        assert conn.execute("SELECT count(*) FROM blob").fetchone()[0] == 2


def test_a_file_touched_meanwhile_is_kept(client, store):
    _, old = photo(client, jpeg())  # young: inside the grace period
    report = shrink.run(store, apply=True)
    assert report.kept == 1 and store.blob_path(old).is_file()


def test_rotation_is_kept(client, store):
    # orientation 6: displayed turned clockwise, so the red left half ends up on top
    _, old = photo(client, jpeg((3200, 1600), orientation=6))
    age(store)
    shrink.run(store, apply=True)
    with store.connect() as conn:
        (new,) = conn.execute("SELECT sha256 FROM capture_blob").fetchone()
    with Image.open(store.blob_path(new)) as im:
        assert im.size == (1280, 2560)  # upright: taller than wide
        assert not im.getexif().get(0x0112)
        top = im.convert("RGB").getpixel((600, 100))
    assert isinstance(top, tuple)
    r, _, b = top
    assert r > 200 and b < 60  # top: red


def test_skips_what_is_not_shrinkable(client, store):
    photo(client, jpeg((2560, 1000)), name="small.jpg")  # at the limit
    out = BytesIO()
    Image.new("RGB", (3000, 3000), "white").save(out, "PNG")
    photo(client, out.getvalue(), name="s.png", mime="image/png")  # a PNG
    photo(client, b"not an image at all", name="x.jpg")  # unreadable
    out = BytesIO()
    noise = Image.frombytes("RGB", (2700, 2700), os.urandom(2700 * 2700 * 3))
    noise.save(out, "JPEG", quality=20)
    photo(client, out.getvalue(), name="tiny.jpg")  # re-encoding would not help
    age(store)
    before = state(store)
    report = shrink.run(store, apply=True)
    assert report.items == []
    assert (report.small, report.other_types, report.unreadable) == (1, 1, 1)
    assert report.bigger == 1
    assert state(store) == before


def test_resumes_after_a_stop(client, store, monkeypatch):
    photo(client, jpeg((3200, 2400)), text="one")
    photo(client, jpeg((3300, 2400)), text="two")
    age(store)

    def stop(sha):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        shrink.run(store, apply=True, progress=stop)  # after the first
    with store.connect() as conn:
        shas = [r[0] for r in conn.execute("SELECT sha256 FROM capture_blob")]
    assert sum(max(dims(store.blob_path(s))) == 2560 for s in shas) == 1
    report = shrink.run(store, apply=True)
    assert len(report.items) == 1 and report.small == 1


def test_refuses_while_another_run_holds_the_lock(client, store):
    import fcntl

    photo(client, jpeg())
    with open(store.dir / shrink.LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(shrink.ShrinkError, match="running"):
            shrink.run(store, apply=True)
        assert len(shrink.run(store).items) == 1  # a dry run only reads


def test_a_conflict_rolls_back(client, store):
    _, old = photo(client, jpeg())
    age(store)
    # an active job already on the new file's address would collide: make it
    data = shrink.smaller(store.blob_path(old))
    assert data
    new = hashlib.sha256(data[0]).hexdigest()
    with store.connect() as conn:
        cid = conn.execute("SELECT capture_id FROM capture_blob").fetchone()[0]
        conn.execute(  # the capture's own job on old is queued already
            "INSERT INTO job (kind, capture_id, source_sha256, run_after,"
            " created_at, updated_at) VALUES ('ingest', ?, ?, 'x', 'x', 'x')",
            (cid, new),
        )
    before = state(store)
    report = shrink.run(store, apply=True)
    assert report.failed == 1 and report.items == []
    assert state(store)[0] == before[0]  # no reference moved
    assert store.blob_path(old).is_file()
