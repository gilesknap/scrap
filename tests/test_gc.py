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


@pytest.mark.xdist_group("timing")  # one worker: see conftest.py
def test_body_refs_is_linear_and_finds_every_address():
    a, b = "a" * 64, "b" * 64
    text = f"![](/api/blobs/{a}/preview?size=2048) [f](/api/blobs/{b}?download=1) `x`"
    assert body_refs(text) == {a, b}
    assert body_refs("/api/blobs/" + "a" * 63) == set()
    start = time.perf_counter()
    body_refs("/api/blobs/" + "a" * 63 + "`[](" * 200_000)
    assert time.perf_counter() - start < 5  # milliseconds; quadratic is minutes


def test_a_file_mentioned_only_in_code_or_odd_markdown_is_kept(client, store):
    """body_refs is not the Markdown parser: an address in code, a full URL, an HTML
    comment or broken Markdown still keeps its file, as gc deletes what it misses."""
    ref, _ = photo(client)
    shas = [put(store, f"mention {n}".encode()) for n in range(7)]
    orphan = put(store, b"orphan")
    a = [f"/api/blobs/{sha}" for sha in shas]
    body = (
        f"```\n![]({a[0]}/preview?size=2048)\n```\n\n"
        f"    indented {a[1]}\n\n"
        f"inline `{a[2]}?download=1`\n\n"
        f"https://scrap.example{a[3]}/preview?size=480\n\n"
        f"<!-- {a[4]} -->\n\n"
        f"![broken]({a[5]}\n\n"
        f"| [[x\\|{a[6]}]] |"
    )
    client.patch(
        f"/api/pages/{ref['page_id']}", json={"base_rev": 1, "body": body}
    ).raise_for_status()
    age_all(store)
    assert gc.collect(store, delete=True).shas == [orphan]
    for sha in shas:
        assert store.blob_path(sha).is_file(), sha


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

    monkeypatch.setattr("os.utime", deleted_meanwhile)
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


def test_removing_an_embed_hides_the_photo_and_counts_other_pages(client, store):
    ref, sha = photo(client)
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert page["removed"] == []
    assert client.get("/api/pages").json()[0]["thumb"] == sha
    assert client.get(f"/api/blobs/{sha}/uses?page={ref['page_id']}").json() == {
        "pages": 0
    }
    other, _ = photo(client, b"other", "Other page")
    client.patch(
        f"/api/pages/{other['page_id']}",
        json={"base_rev": 1, "body": f"![](/api/blobs/{sha}/preview?size=2048)"},
    ).raise_for_status()
    uses = client.get(f"/api/blobs/{sha}/uses?page={ref['page_id']}").json()
    assert uses == {"pages": 1}
    client.delete(f"/api/pages/{other['page_id']}").raise_for_status()  # the trash
    assert client.get(f"/api/blobs/{sha}/uses?page={ref['page_id']}").json() == {
        "pages": 0
    }
    edited = client.patch(
        f"/api/pages/{ref['page_id']}", json={"base_rev": 1, "body": "A photo"}
    ).json()
    assert edited["removed"] == [sha]
    rows = {p["id"]: p for p in client.get("/api/pages").json()}
    assert rows[ref["page_id"]]["thumb"] is None
    assert client.get(f"/api/blobs/{'d' * 64}/uses?page=x").status_code == 404
    # Still the capture's: gc keeps it (and its Claude results) while it has a capture
    age_all(store)
    assert sha not in gc.collect(store, delete=True).shas


@pytest.mark.parametrize("delete", [False, True])
def test_a_file_left_aside_by_a_stopped_run_is_put_back(client, store, delete):
    """A run that stopped between the rename and the relink strands a live file."""
    page, sha = photo(client, b"left aside")
    path = store.blob_path(sha)
    os.rename(path, path.with_name(f"{gc.ASIDE}{sha}"))
    report = gc.collect(store, delete=delete)
    assert report.restored == 1 and "put back 1 files" in report.text()
    assert sha not in report.shas
    assert path.read_bytes() == b"left aside"
    assert [p.name for p in path.parent.iterdir()] == [sha]
    assert client.get(f"/api/blobs/{sha}").status_code == 200


def test_an_aside_whose_name_is_taken_goes_and_an_unused_one_is_deleted(store):
    taken = put(store, b"written again")
    path = store.blob_path(taken)
    os.link(path, path.with_name(f"{gc.ASIDE}{taken}"))
    unused = put(store, b"nothing uses me")
    upath = store.blob_path(unused)
    os.rename(upath, upath.with_name(f"{gc.ASIDE}{unused}"))
    report = gc.collect(store, delete=True)
    assert report.restored == 1  # only the one whose name was free
    assert sorted(report.shas) == sorted([taken, unused])  # then both are unused
    assert not path.exists() and not upath.exists()
    assert not list(store.files.rglob(f"{gc.ASIDE}*"))


def _stamp(days):
    return time.strftime(
        "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - days * DAY)
    )


def _model_run(conn, cid, sha, days, parent=None, status="ok"):
    return conn.execute(
        "INSERT INTO model_run (capture_id, source_sha256, parent_id, purpose, model,"
        " prompt_version, request, status, started_at)"
        " VALUES (?, ?, ?, 'ingest', 'm', 'v', '{}', ?, ?) RETURNING id",
        (cid, sha, parent, status, _stamp(days)),
    ).fetchone()[0]


def _enrich_run(conn, page, days, status="ok", request="{}"):
    return conn.execute(
        "INSERT INTO enrich_run (page_id, model, prompt_version, request, status,"
        " started_at) VALUES (?, 'm', 'v', ?, ?, ?) RETURNING id",
        (page, request, status, _stamp(days)),
    ).fetchone()[0]


def _ids(store, table):
    with store.connect() as conn:
        return {r[0] for r in conn.execute(f"SELECT id FROM {table}")}


def test_old_runs_are_counted_then_deleted_and_the_rest_kept(client, store):
    a, sha_a = photo(client, b"photo a", "A")
    b, sha_b = photo(client, b"photo b", "B")
    pa, pb = a["page_id"], b["page_id"]
    with store.connect() as conn:
        # model runs: a has an old unreferenced one, an old derived-referenced one,
        # a recent one, and a newest-but-old one; b has only one old run (its latest)
        m_old = _model_run(conn, a["capture_id"], sha_a, 90)
        m_derived = _model_run(conn, a["capture_id"], sha_a, 80)
        m_old2 = _model_run(conn, a["capture_id"], sha_a, 70)
        m_recent = _model_run(conn, a["capture_id"], sha_a, 5)
        m_latest_b = _model_run(conn, b["capture_id"], sha_b, 200)
        conn.execute(
            "INSERT INTO derived (capture_id, source_sha256, kind, version, producer,"
            " run_id, text, created_at) VALUES (?, ?, 'ocr', 1, 'm', ?, 'x', ?)",
            (a["capture_id"], sha_a, m_derived, now()),
        )
        # enrich runs: page a: old, referenced, running, recent; page b: old, latest
        e_old = _enrich_run(conn, pa, 90)
        e_ref = _enrich_run(conn, pa, 60)
        e_running = _enrich_run(conn, pa, 99, status="running")
        e_recent = _enrich_run(conn, pa, 3)
        e_old_b = _enrich_run(conn, pb, 100)
        e_latest_b = _enrich_run(conn, pb, 95)
        conn.execute(
            "INSERT INTO enrichment (page_id, run_id, producer, updated_at)"
            " VALUES (?, ?, 'm', ?)",
            (pa, e_ref, now()),
        )
    dry = gc.collect(store)
    assert (dry.model_runs, dry.enrich_runs) == (2, 2)
    assert "2 model runs and 2 enrich runs older than the retention" in dry.text()
    assert _ids(store, "model_run") >= {m_old, m_old2}  # a dry run deletes nothing
    assert _ids(store, "enrich_run") >= {e_old, e_old_b}

    done = gc.collect(store, delete=True)
    assert (done.model_runs, done.enrich_runs) == (2, 2)
    assert _ids(store, "model_run") == {m_derived, m_recent, m_latest_b}
    assert _ids(store, "enrich_run") == {e_ref, e_recent, e_latest_b, e_running}
    again = gc.collect(store, delete=True)
    assert (again.model_runs, again.enrich_runs) == (0, 0)


def test_the_newest_ok_related_run_of_a_page_is_kept(client, store):
    a, _ = photo(client)
    pa = a["page_id"]
    related = '{"purpose": "related"}'
    with store.connect() as conn:
        r_old = _enrich_run(conn, pa, 100, request=related)
        r_new = _enrich_run(conn, pa, 90, request=related)
        r_failed = _enrich_run(conn, pa, 80, status="error", request=related)
        e_latest = _enrich_run(conn, pa, 70)  # the page's newest run, not related
    done = gc.collect(store, delete=True)
    assert done.enrich_runs == 2
    assert _ids(store, "enrich_run") == {r_new, e_latest}
    assert r_old not in _ids(store, "enrich_run") and r_failed not in _ids(
        store, "enrich_run"
    )


def test_a_kept_turn_keeps_the_turns_it_continues(client, store):
    a, sha = photo(client)
    with store.connect() as conn:
        first = _model_run(conn, a["capture_id"], sha, 100)
        second = _model_run(conn, a["capture_id"], sha, 90, parent=first)
        third = _model_run(conn, a["capture_id"], sha, 80, parent=second)
        unrelated = _model_run(conn, a["capture_id"], "other", 100)
        _model_run(conn, a["capture_id"], "other", 99)  # the latest of "other"
    done = gc.collect(store, delete=True)
    assert done.model_runs == 1
    assert {first, second, third}.isdisjoint({unrelated}) and unrelated not in _ids(
        store, "model_run"
    )
    assert {first, second, third} <= _ids(store, "model_run")


def test_deleted_runs_free_the_jpeg_they_sent_for_the_next_run(client, store):
    a, sha = photo(client)
    sent = put(store, b"sent jpeg")
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO model_run (capture_id, source_sha256, purpose, model,"
            " prompt_version, sent_sha256, request, status, started_at)"
            " VALUES (?, ?, 'ingest', 'm', 'v', ?, '{}', 'ok', ?)",
            (a["capture_id"], sha, sent, _stamp(90)),
        )
        _model_run(conn, a["capture_id"], sha, 80)  # newer: the old one is not latest
    age_all(store)
    assert gc.collect(store, delete=True).model_runs == 1
    assert store.blob_path(sent).is_file()  # still referenced when files were counted
    assert gc.collect(store, delete=True).shas == [sent]


def test_run_retention_is_a_setting(client, store, capsys):
    a, sha = photo(client)
    with store.connect() as conn:
        _model_run(conn, a["capture_id"], sha, 10)
        _model_run(conn, a["capture_id"], sha, 9)
    assert gc.collect(store, run_days=30).model_runs == 0
    assert gc.collect(store, run_days=5).model_runs == 1
    assert gc.collect(store).model_runs == 0
    with pytest.raises(gc.GcError, match="at least 1 day"):
        gc.collect(store, run_days=0)
    main(["gc", "--run-days", "5", "--data-dir", str(store.dir)])
    assert "1 model runs and 0 enrich runs older" in capsys.readouterr().out
    assert len(_ids(store, "model_run")) == 2
    main(["gc", "--delete", "--run-days", "5", "--data-dir", str(store.dir)])
    assert len(_ids(store, "model_run")) == 1


def test_a_deleting_run_refuses_while_another_holds_the_lock(client, store, capsys):
    import fcntl

    sha = put(store, b"unused")
    with open(store.dir / gc.LOCK, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(SystemExit, match="another scrap gc is deleting"):
            main(["gc", "--delete", "--data-dir", str(store.dir)])
        assert store.blob_path(sha).exists()
        main(["gc", "--data-dir", str(store.dir)])  # counting needs no lock
    main(["gc", "--delete", "--data-dir", str(store.dir)])
    assert not store.blob_path(sha).exists()


def test_a_failed_put_back_is_not_reported_as_unreadable_references(
    client, store, monkeypatch
):
    def boom(_store):
        raise OSError("disk full")

    monkeypatch.setattr(gc, "_restore", boom)
    with pytest.raises(gc.GcError, match="cannot put back a file"):
        gc.collect(store)
