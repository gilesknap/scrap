import hashlib
import os
import sqlite3
import time
from io import BytesIO

import pytest

from scrap import gc
from scrap.__main__ import main
from scrap.store import Store, body_refs, new_ulid, now

DAY = 24 * 3600


def old(path, days=2):
    t = time.time() - days * DAY
    os.utime(path, (t, t))


def put(store, data: bytes, mime="image/png", age=2):
    """A stored file with its blob row, as a capture leaves it, but used by nothing."""
    sha, size = store.put_blob(BytesIO(data))
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO blob VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (sha, mime, size, "2026-01-01T00:00:00.000Z"),
        )
    if age:
        old(store.blob_path(sha), age)
    return sha


def photo(client, data=b"photo bytes", text="A photo"):
    r = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": text},
        files=[("file", ("p.png", data, "image/png"))],
    )
    assert r.status_code == 201, r.text
    return r.json(), hashlib.sha256(data).hexdigest()


@pytest.fixture
def store(client, tmp_path):
    s = Store(tmp_path / "data")
    for path in s.files.rglob("*"):
        if path.is_file():
            old(path)
    return s


def age_all(store):
    for path in store.files.rglob("*"):
        if path.is_file():
            old(path)


def test_body_refs_is_linear_and_finds_every_address():
    a, b = "a" * 64, "b" * 64
    text = f"![](/api/blobs/{a}/preview?size=2048) [f](/api/blobs/{b}?download=1) `x`"
    assert body_refs(text) == {a, b}
    assert body_refs("/api/blobs/" + "a" * 63) == set()
    start = time.perf_counter()
    body_refs("/api/blobs/" + "a" * 63 + "`[](" * 200_000)
    assert time.perf_counter() - start < 1


def test_dry_run_is_the_default_and_counts(client, store):
    page, used = photo(client)
    orphan = put(store, b"nobody uses me")
    age_all(store)
    report = gc.collect(store)
    assert not report.deleted
    assert report.shas == [orphan] and report.unused == 1
    assert report.unused_bytes == len(b"nobody uses me") and report.rows == 1
    assert store.blob_path(orphan).is_file() and store.blob_path(used).is_file()
    report = gc.collect(store, delete=True)
    assert report.deleted and report.shas == [orphan]
    assert not store.blob_path(orphan).exists()
    assert store.blob_path(used).is_file()
    with store.connect() as conn:
        row = conn.execute("SELECT 1 FROM blob WHERE sha256 = ?", (orphan,))
        assert not row.fetchone()
    assert gc.collect(store, delete=True).shas == []


def test_every_kind_of_reference_keeps_a_file(client, store):
    ref, captured = photo(client)
    in_trash, in_body, derived, job, run, sent = (
        put(store, f"file {n}".encode()) for n in range(6)
    )
    orphan = put(store, b"orphan")
    # A trashed page embedding a file
    trashed, _ = photo(client, b"other", "Trashed")
    client.patch(
        f"/api/pages/{trashed['page_id']}",
        json={"base_rev": 1, "body": f"![](/api/blobs/{in_trash}/preview?size=2048)"},
    ).raise_for_status()
    client.delete(f"/api/pages/{trashed['page_id']}").raise_for_status()
    client.patch(
        f"/api/pages/{ref['page_id']}",
        json={"base_rev": 1, "body": f"see [this](/api/blobs/{in_body}?download=1)"},
    ).raise_for_status()
    cid, stamp = ref["capture_id"], now()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO derived (capture_id, source_sha256, kind, version, producer,"
            " text, created_at) VALUES (?, ?, 'ocr', 1, 'human', 'x', ?)",
            (cid, derived, stamp),
        )
        conn.execute(
            "INSERT INTO job (kind, capture_id, source_sha256, state, run_after,"
            " created_at, updated_at) VALUES ('ingest', ?, ?, 'done', ?, ?, ?)",
            (cid, job, stamp, stamp, stamp),
        )
        conn.execute(
            "INSERT INTO model_run (capture_id, source_sha256, purpose, model,"
            " prompt_version, sent_sha256, request, started_at)"
            " VALUES (?, ?, 'ingest', 'm', 'v', ?, '{}', ?)",
            (cid, run, sent, stamp),
        )
    age_all(store)
    assert gc.collect(store, delete=True).shas == [orphan]
    for sha in (captured, in_trash, in_body, derived, job, run, sent):
        assert store.blob_path(sha).is_file(), sha


def test_grace_period_keeps_young_files_and_leftover_uploads(store):
    young = put(store, b"just uploaded", age=0)
    orphan = put(store, b"old")
    with store.connect() as conn:  # a record whose file is gone, recorded just now
        conn.execute(
            "INSERT INTO blob VALUES (?, 'image/png', 1, ?)", ("c" * 64, now())
        )
    fresh_tmp = store.files / ".up-fresh"
    stale_tmp = store.files / ".up-stale"
    fresh_tmp.write_bytes(b"x")
    stale_tmp.write_bytes(b"yy")
    old(stale_tmp)
    (store.files / "README").write_text("not mine")
    old(store.files / "README")
    report = gc.collect(store, delete=True)
    assert report.shas == [orphan] and report.young == 2
    assert report.temp == 1 and report.temp_bytes == 2
    assert store.blob_path(young).is_file() and fresh_tmp.is_file()
    assert not stale_tmp.exists() and (store.files / "README").is_file()
    assert gc.collect(store, delete=True, grace_hours=0).shas == sorted(
        [young, "c" * 64]
    )


def test_a_file_used_again_after_the_first_look_is_kept(client, store):
    """The race: a page embeds an unused file between the dry look and the delete."""
    ref, _ = photo(client)
    orphan = put(store, b"about to be used")

    def embed():
        client.patch(
            f"/api/pages/{ref['page_id']}",
            json={"base_rev": 1, "body": f"![](/api/blobs/{orphan})"},
        ).raise_for_status()
        yield None

    report = gc.collect(store, delete=True, _between=embed())
    assert report.shas == [] and report.kept == 1
    assert store.blob_path(orphan).is_file()


def test_an_upload_of_the_same_bytes_while_deleting_keeps_the_file(store):
    orphan = put(store, b"uploaded again")

    def upload():
        assert store.put_blob(BytesIO(b"uploaded again"))[0] == orphan  # touches it
        yield None

    report = gc.collect(store, delete=True, _between=upload())
    assert report.shas == [] and report.kept == 1
    assert store.blob_path(orphan).read_bytes() == b"uploaded again"


def test_delete_puts_back_a_file_touched_just_before_the_rename(store, monkeypatch):
    orphan = put(store, b"touched")
    path = store.blob_path(orphan)
    rename = os.rename

    def touch_then_rename(src, dst):
        os.utime(src)  # an upload of the same bytes, just before gc moves it aside
        rename(src, dst)

    monkeypatch.setattr(gc.os, "rename", touch_then_rename)
    assert not gc._delete(store, orphan, path, time.time() - DAY)
    assert path.read_bytes() == b"touched"
    assert [p.name for p in path.parent.iterdir()] == [orphan]


def test_put_blob_writes_the_file_again_if_gc_deleted_it(store, monkeypatch):
    sha = put(store, b"gone")
    path = store.blob_path(sha)
    utime = os.utime

    def deleted_meanwhile(p, *a, **kw):
        if str(p) == str(path) and path.exists():
            path.unlink()  # gc deleted it between the link and the touch
            raise FileNotFoundError(p)
        return utime(p, *a, **kw)

    monkeypatch.setattr("scrap.store.os.utime", deleted_meanwhile)
    assert store.put_blob(BytesIO(b"gone"))[0] == sha
    assert path.read_bytes() == b"gone"


def test_refuses_when_the_references_cannot_be_read(store, monkeypatch):
    orphan = put(store, b"orphan")

    def broken(conn):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(gc, "in_use", broken)
    with pytest.raises(gc.GcError, match="nothing was deleted"):
        gc.collect(store, delete=True)
    assert store.blob_path(orphan).is_file()
    with pytest.raises(gc.GcError, match="no database"):
        gc.collect(Store(store.dir / "nowhere"), delete=True)


def test_refuses_when_a_table_is_missing(store):
    orphan = put(store, b"orphan")
    with store.connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DROP TABLE model_run")
    with pytest.raises(gc.GcError):
        gc.collect(store, delete=True)
    assert store.blob_path(orphan).is_file()


def test_deleting_drops_the_previews_too(store):
    orphan = put(store, b"orphan")
    cache = store.dir / "cache" / "previews" / "480" / orphan[:2] / f"{orphan}.jpg"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"jpeg")
    gc.collect(store, delete=True)
    assert not cache.exists()


def test_cli_dry_run_by_default_prints_counts_only(client, store, capsys):
    photo(client, b"secret photo", "Secret page title")
    orphan = put(store, b"orphan bytes")
    main(["gc", "--data-dir", str(store.dir)])
    out = capsys.readouterr().out
    assert "would delete (dry run" in out and "1 unused files" in out
    assert "Secret" not in out and orphan not in out
    assert store.blob_path(orphan).is_file()
    main(["gc", "--delete", "--dry-run", "--data-dir", str(store.dir)])
    assert store.blob_path(orphan).is_file()
    main(["gc", "--delete", "--data-dir", str(store.dir)])
    assert "deleted 1 unused files" in capsys.readouterr().out.splitlines()[-1]
    assert not store.blob_path(orphan).exists()
    with pytest.raises(SystemExit, match="scrap gc: no database"):
        main(["gc", "--data-dir", str(store.dir / "none")])

