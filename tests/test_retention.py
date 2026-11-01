"""Retention in scrap gc (#276): the trash purged after N days, finished jobs pruned,
the size report, and the purge date the PWA and MCP show."""

import hashlib
import os
import sqlite3
import time

import pytest

from scrap import gc, orphans, retention, sizes
from scrap.__main__ import main
from scrap.app import create_app
from scrap.store import ConflictError, Store, new_ulid, now, topics
from test_mcp import ok
from test_orphans import OCT, age, describe, edit, orphan_pages, unembed

DAY = 24 * 3600
OLD = "2026-01-01T00:00:00.000Z"  # trashed long ago
# Every table holding a page's rows, and its column naming the page
PAGE_TABLES = (
    ("page_rev", "page_id"), ("capture", "page_id"), ("chunk", "page_id"),
    ("tag", "page_id"), ("page_meta_rev", "page_id"), ("enrich_job", "page_id"),
    ("enrich_run", "page_id"), ("enrichment", "page_id"), ("model_tag", "page_id"),
    ("related", "page_id"), ("related", "other_id"), ("writeup", "page_id"),
    ("writeup_guidance", "page_id"), ("topic_source", "page_id"),
)  # fmt: skip
CAPTURE_TABLES = ("capture_blob", "job", "model_run", "derived", "image_guidance")


@pytest.fixture
def store(client, tmp_path, monkeypatch):
    monkeypatch.setattr(orphans, "clock", lambda: OCT)
    monkeypatch.delenv("SCRAP_NOTIFY_URL", raising=False)
    monkeypatch.delenv("SCRAP_TRASH_DAYS", raising=False)
    return Store(tmp_path / "data")


def photo(client, data=b"photo bytes", text="A photo zebra"):
    r = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": text},
        files=[("file", ("p.png", data, "image/png"))],
    )
    assert r.status_code == 201, r.text
    return r.json(), hashlib.sha256(data).hexdigest()


def age_files(store, days=2):
    t = time.time() - days * DAY
    for path in store.files.rglob("*"):
        if path.is_file():
            os.utime(path, (t, t))


def trash(client, store, page_id, when=OLD):
    assert client.delete(f"/api/pages/{page_id}").status_code == 204
    with store.connect() as conn:
        conn.execute("UPDATE page SET deleted_at = ? WHERE id = ?", (when, page_id))


def dump(store) -> list[str]:
    with store.connect() as conn:
        return list(conn.iterdump())


def furnish(store, page_id, cid, sha, other):
    """Give a page a row in every table that can hold one: Claude's results and runs,
    jobs, an image's guidance, tags, a write-up, related picks both ways, and a topic membership."""
    t = now()
    with store.connect() as conn:
        run = conn.execute(
            "INSERT INTO model_run (capture_id, source_sha256, purpose, model,"
            " prompt_version, request, status, started_at)"
            " VALUES (?, ?, 'ingest', 'm', 'v', '{}', 'ok', ?)",
            (cid, sha, t),
        ).lastrowid
        conn.execute(
            "INSERT INTO derived (capture_id, source_sha256, kind, version, producer,"
            " run_id, text, created_at) VALUES (?, ?, 'ocr', 1, 'm', ?, 'zebra', ?)",
            (cid, sha, run, t),
        )
        erun = conn.execute(
            "INSERT INTO enrich_run (page_id, model, prompt_version, request, status,"
            " started_at) VALUES (?, 'm', 'v', '{}', 'ok', ?)",
            (page_id, t),
        ).lastrowid
        conn.execute(
            "INSERT INTO enrichment VALUES (?, ?, 'm', 's', NULL, NULL, ?)",
            (page_id, erun, t),
        )
        conn.execute(
            "INSERT INTO writeup (page_id, producer, run_id, prompt_version,"
            " text, created_at) VALUES (?, 'm', ?, 'v', 'w', ?)",
            (page_id, erun, t),
        )
        conn.execute(
            "INSERT INTO writeup_guidance VALUES (?, 'g', 'me', ?)", (page_id, t)
        )
        conn.execute(
            "INSERT INTO image_guidance VALUES (?, ?, 'g', 'me', ?)", (cid, sha, t)
        )
        conn.execute(
            "INSERT INTO model_tag VALUES (?, 'mt', 'on', 'm', ?)", (page_id, t)
        )
        conn.execute(
            "INSERT INTO enrich_job (page_id, reason, state, run_after, created_at,"
            " updated_at) VALUES (?, 'save', 'done', ?, ?, ?)",
            (page_id, t, t, t),
        )
        conn.execute("INSERT INTO related VALUES (?, ?, 1)", (page_id, other))
        conn.execute("INSERT INTO related VALUES (?, ?, 1)", (other, page_id))
        topic = topics.create(conn, "Zebras", "zebras", "zebras", "claude", t)
        assert topic
        topics.add_sources(conn, topic, [page_id, other], "claude", t)
        conn.execute(
            "INSERT INTO page_meta_rev (page_id, author, source, kind_before,"
            " kind_after, fixed_before, fixed_after, tags_before, tags_after,"
            " created_at, updated_at) VALUES (?, 'me', 'web', 'note', 'note', 0, 0,"
            " '[]', '[\"x\"]', ?, ?)",
            (page_id, t, t),
        )
        conn.execute("INSERT INTO tag VALUES (?, 'x')", (page_id,))
    return topic


def leftovers(store, page_id, cid) -> dict[str, int]:
    with store.connect() as conn:
        found = {
            f"{t}.{col}": conn.execute(
                f"SELECT count(*) FROM {t} WHERE {col} = ?", (page_id,)
            ).fetchone()[0]
            for t, col in PAGE_TABLES
        }
        found |= {
            t: conn.execute(
                f"SELECT count(*) FROM {t} WHERE capture_id = ?", (cid,)
            ).fetchone()[0]
            for t in CAPTURE_TABLES
        }
    return {k: n for k, n in found.items() if n}


def test_a_page_long_in_the_trash_is_purged_with_everything_on_it(client, store, note):
    ref, sha = photo(client)
    other = note("A live page")
    furnish(store, ref["page_id"], ref["capture_id"], sha, other["page_id"])
    assert leftovers(store, ref["page_id"], ref["capture_id"])
    trash(client, store, ref["page_id"])
    age_files(store)
    report = gc.collect(store, delete=True)
    assert report.purged == 1 and sha in report.shas
    assert "purged 1 pages in the trash more than 30 days" in report.text()
    assert leftovers(store, ref["page_id"], ref["capture_id"]) == {}
    with store.connect() as conn:
        assert not conn.execute("SELECT 1 FROM page WHERE id = ?", (ref["page_id"],))\
            .fetchall()  # fmt: skip
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('integrity-check')")
        assert not conn.execute("SELECT 1 FROM blob WHERE sha256 = ?", (sha,))\
            .fetchall()  # fmt: skip
    assert not store.blob_path(sha).exists()  # an unused file now: deleted
    hits = client.get("/api/search?q=zebra").json()
    assert ref["page_id"] not in {h["id"] for h in hits}
    live = client.get(f"/api/pages/{other['page_id']}")  # untouched
    assert live.status_code == 200 and live.json()["title"] == "A live page"
    with store.connect() as conn:  # its own rows stay: its source membership too
        assert (
            conn.execute(
                "SELECT count(*) FROM topic_source WHERE page_id = ?",
                (other["page_id"],),
            ).fetchone()[0]
            == 1
        )


def test_a_page_trashed_recently_is_kept(client, store, note):
    ref = note("Recent")
    trash(client, store, ref["page_id"], retention.stamp(29))
    old = note("Old")
    trash(client, store, old["page_id"], retention.stamp(31))
    report = gc.collect(store, delete=True)
    assert report.purged == 1
    assert [r["id"] for r in store.trash(10)] == [ref["page_id"]]
    assert gc.collect(store, delete=True, trash_days=60).purged == 0


def test_the_purge_s_files_wait_for_the_grace_period(client, store):
    ref, sha = photo(client)
    trash(client, store, ref["page_id"])
    report = gc.collect(store, delete=True)  # the file is minutes old
    assert report.purged == 1 and report.young == 1 and sha not in report.shas
    assert store.blob_path(sha).is_file()
    age_files(store)
    assert sha in gc.collect(store, delete=True).shas
    assert not store.blob_path(sha).exists()


def test_a_dry_run_counts_the_purge_and_changes_nothing(client, store, capsys):
    ref, sha = photo(client)
    trash(client, store, ref["page_id"])
    age_files(store)
    before = dump(store)
    report = gc.collect(store)
    assert (report.purged, report.unused, report.deleted) == (1, 1, False)
    assert sha in report.shas  # the file the purge would free, counted
    assert "would purge 1 pages in the trash more than 30 days" in report.text()
    main(["gc", "--data-dir", str(store.dir), "--delete", "--dry-run"])
    assert "would purge 1 pages" in capsys.readouterr().out
    assert dump(store) == before and store.blob_path(sha).is_file()


def test_no_backup_means_no_purge(client, store):
    """deploy/scrap-gc and the chart's CronJob run --dry-run when there is no
    recent backup: then the trash is only counted."""
    ref, _ = photo(client)
    trash(client, store, ref["page_id"])
    main(["gc", "--data-dir", str(store.dir), "--dry-run"])
    assert [r["id"] for r in store.trash(10)] == [ref["page_id"]]


def test_a_trashed_topic_is_never_purged_and_its_key_stays_a_veto(client, store):
    with store.connect() as conn:
        topic = topics.create(
            conn, "RTEMS IOCs", "rtems-iocs", "rtems", "claude", now()
        )
    trash(client, store, topic)
    assert gc.collect(store, delete=True).purged == 0
    [row] = store.trash(10)
    assert row["topic"] is True and row["purge_at"] is None
    with store.connect() as conn:  # discovery cannot make it again
        assert topics.create(conn, "RTEMS IOCs", "rtems-iocs", "r2", "x", now()) is None
        assert [t["key"] for t in topics.every(conn)] == ["rtems-iocs"]


def test_a_purged_review_page_lets_its_orphans_go(client, store):
    ref, sha = unembed(client, store)
    describe(store, ref["capture_id"], sha, "A cat")
    gc.collect(store, delete=True)
    [page] = orphan_pages(client)
    trash(client, store, page["id"])
    age(store)
    report = gc.collect(store, delete=True)
    assert (report.purged, report.let_go) == (1, 1) and sha in report.shas
    for table in ("capture_blob", "derived", "job", "model_run"):  # the photo's
        assert leftovers(store, "-", ref["capture_id"]).get(table) is None
    assert not store.blob_path(sha).exists()
    assert "(and 1 orphaned files)" in report.text()
    with store.connect() as conn:
        assert not conn.execute(
            "SELECT 1 FROM capture_blob WHERE sha256 = ?", (sha,)
        ).fetchall()
    # its page stays as it was, and nothing is gathered again
    assert client.get(f"/api/pages/{ref['page_id']}").json()["body"] == "A photo"
    assert gc.collect(store, delete=True).orphans == 0
    assert orphan_pages(client) == []


def test_an_item_cut_from_a_review_page_goes_with_it_and_a_kept_one_stays(
    client, store, note
):
    _, dropped = unembed(client, store, "One", b"one")
    _, kept = unembed(client, store, "Two", b"two")
    gc.collect(store, delete=True)
    [page] = orphan_pages(client)
    keeper = note(f"Kept here ![](/api/blobs/{kept}/preview?size=2048)")
    edit(client, page["id"], "Looked through")  # both cut; one pasted elsewhere
    trash(client, store, page["id"])
    age(store)
    report = gc.collect(store, delete=True)
    assert report.let_go == 1 and dropped in report.shas and kept not in report.shas
    assert store.blob_path(kept).is_file()
    assert client.get(f"/api/pages/{keeper['page_id']}").status_code == 200


def test_a_purge_leaves_the_files_of_a_trashed_holder_alone(client, store):
    """An orphan whose page is in the trash too is not let go: that page may come
    back, and its own purge frees the file."""
    ref, sha = unembed(client, store)
    gc.collect(store, delete=True)
    [page] = orphan_pages(client)
    trash(client, store, page["id"])
    trash(client, store, ref["page_id"], retention.stamp(1))
    age(store)
    report = gc.collect(store, delete=True)
    assert (report.purged, report.let_go) == (1, 0)
    assert store.blob_path(sha).is_file()


def jobs(store, table):
    with store.connect() as conn:
        return {r[0]: r[1] for r in conn.execute(f"SELECT id, state FROM {table}")}


def test_finished_jobs_are_pruned_but_each_latest_is_kept(client, store, note):
    ref, sha = photo(client)
    page = note("A note")["page_id"]
    stale = retention.stamp(40)
    with store.connect() as conn:
        rows = [
            ("done", stale), ("dead", stale), ("done", now()), ("queued", stale),
            ("done", stale),  # the newest: kept
        ]  # fmt: skip
        conn.execute("DELETE FROM job")
        for state, at in rows:
            conn.execute(
                "INSERT INTO job (kind, capture_id, source_sha256, state, run_after,"
                " created_at, updated_at) VALUES ('ingest', ?, ?, ?, ?, ?, ?)",
                (ref["capture_id"], sha, state, at, at, at),
            )
        conn.execute("DELETE FROM enrich_job")
        for reason, state in [("save", "done"), ("save", "dead"), ("save", "done"),
                              ("related", "done")]:  # fmt: skip
            conn.execute(
                "INSERT INTO enrich_job (page_id, reason, state, run_after,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (page, reason, state, stale, stale, stale),
            )
    before_jobs, before_texts = jobs(store, "job"), jobs(store, "enrich_job")
    report = gc.collect(store)
    assert (report.jobs, report.enrich_jobs) == (2, 2)
    assert "2 ingest jobs and 2 enrich jobs finished more than 30 days ago" in (
        report.text()
    )
    assert jobs(store, "job") == before_jobs  # a dry run
    report = gc.collect(store, delete=True)
    assert (report.jobs, report.enrich_jobs) == (2, 2)
    ids = sorted(before_jobs)
    assert sorted(jobs(store, "job")) == ids[2:]  # recent, queued and the newest
    texts = sorted(before_texts)
    assert sorted(jobs(store, "enrich_job")) == texts[2:]  # each reason's newest
    assert gc.collect(store, delete=True, job_days=60).jobs == 0


@pytest.mark.parametrize(
    "args", [["--trash-days", "0"], ["--job-days", "0.5"], ["--trash-days", "nan"]]
)
def test_retention_must_be_a_day_at_least(store, args, capsys):
    with pytest.raises(SystemExit, match="retention must be at least 1 day"):
        main(["gc", "--data-dir", str(store.dir), *args])
    with pytest.raises(SystemExit, match="retention must be at least 1 day"):
        main(["gc", "--data-dir", str(store.dir), "--report", *args])


def test_the_report_measures_the_store_and_changes_nothing(client, store, note, capsys):
    ref, sha = photo(client)
    trash(client, store, ref["page_id"], retention.stamp(40))
    note("A live page")
    before = dump(store)
    r = sizes.measure(store)
    assert dump(store) == before
    assert r["files"]["trash_only"] == {"files": 1, "bytes": len(b"photo bytes")}
    assert r["files"]["unused"]["files"] == 0
    assert r["trash"]["pages"] == 1 and r["trash"]["due"] == 1
    assert r["trash"]["ages"]["30-90 days"] == 1
    tables = {t["table"]: t for t in r["tables"]}
    assert tables["page"]["rows"] == 2 and tables["page"]["bytes"] > 0
    assert "chunk_fts_data" not in tables and "chunk_fts" in tables
    main(["gc", "--data-dir", str(store.dir), "--report"])
    out = capsys.readouterr().out
    assert out.startswith("scrap gc --report: database ")
    assert "used only by pages in the trash" in out
    assert "trashed more than 30 days ago (a purge's): 1" in out
    assert "enrich_job:" in out
    assert dump(store) == before


def test_the_report_counts_call_records_by_month(client, store):
    ref, sha = photo(client)
    with store.connect() as conn:
        for month in ("2026-09", "2026-10", "2026-10"):
            conn.execute(
                "INSERT INTO model_run (capture_id, source_sha256, purpose, model,"
                " prompt_version, request, output, status, started_at)"
                " VALUES (?, ?, 'ingest', 'm', 'v', '{\"a\": 1}', '[]', 'ok', ?)",
                (ref["capture_id"], sha, f"{month}-02T00:00:00.000Z"),
            )
    runs = [r for r in sizes.measure(store)["runs"] if r["table"] == "model_run"]
    assert [(r["month"], r["rows"], r["bytes"]) for r in runs] == [
        ("2026-09", 1, 10), ("2026-10", 2, 20)
    ]  # fmt: skip


def test_the_report_estimates_without_dbstat(client, store, monkeypatch):
    real = sqlite3.Connection.execute

    class Conn(sqlite3.Connection):
        def execute(self, sql, *args):  # type: ignore[override]
            if "dbstat" in sql:
                raise sqlite3.OperationalError("no such table: dbstat")
            return real(self, sql, *args)

    opened = sizes._open
    monkeypatch.setattr(
        sizes, "_open",
        lambda db: sqlite3.connect(f"file:{db}?mode=ro", uri=True,
                                   isolation_level=None, factory=Conn),
    )  # fmt: skip
    assert opened
    r = sizes.measure(store)
    page = next(t for t in r["tables"] if t["table"] == "page")
    assert page["estimated"] and page["bytes"] == 0
    assert "estimated: this SQLite has no dbstat" in sizes.text(r)


def test_the_trash_shows_when_each_page_is_purged(client, store, note, monkeypatch):
    ref = note("Going")
    assert client.delete(f"/api/pages/{ref['page_id']}").status_code == 204
    body = client.get("/api/trash").json()
    assert body["days"] == 30 and body["total"] == 1
    assert client.get("/api/trash?limit=1").json()["total"] == 1
    [row] = body["results"]
    assert row["id"] == ref["page_id"] and row["topic"] is False
    assert row["purge_at"] == retention.purge_at(row["deleted_at"], 30, False)
    assert row["purge_at"][:10] > row["deleted_at"][:10]
    monkeypatch.setenv("SCRAP_TRASH_DAYS", "7")
    [row] = client.get("/api/trash").json()["results"]
    assert row["purge_at"] == retention.purge_at(row["deleted_at"], 7, False)
    monkeypatch.setenv("SCRAP_TRASH_DAYS", "off")
    body = client.get("/api/trash").json()
    assert body["days"] is None and body["results"][0]["purge_at"] is None
    client.post(f"/api/pages/{ref['page_id']}/undelete")
    assert client.get("/api/trash").json()["results"] == []


@pytest.mark.parametrize("value", ["0", "soon", "-3"])
def test_a_bad_trash_setting_stops_the_start(tmp_path, monkeypatch, value):
    monkeypatch.setenv("SCRAP_TRASH_DAYS", value)
    with pytest.raises(SystemExit, match="SCRAP_TRASH_DAYS"):
        create_app(tmp_path / "data")


def test_mcp_shows_the_purge_date_and_says_so(store, monkeypatch):
    c = store.prepare({"id": new_ulid(), "text": "Going"}, [])
    page = store.capture(c, [], "me")[0]["page_id"]
    store.delete_page(page)
    [row] = ok(store, "trash")["results"]
    assert row["purge_at"] == retention.purge_at(row["deleted_at"], 30, False)
    read = ok(store, "read", page=page)["page"]
    assert read["purge_at"] == row["purge_at"]
    dry = ok(store, "undelete", page=page, dry_run=True)
    assert dry["purge_at"] == row["purge_at"]
    assert ok(store, "undelete", page=page)["purge_at"] is None
    from scrap import mcp_server

    text = mcp_server.server(store).instructions or ""
    assert "Nothing deletes a page until it has been in the trash for 30 days" in text
    assert "with when each page\nis purged" in text
    monkeypatch.setenv("SCRAP_TRASH_DAYS", "off")
    text = mcp_server.server(store).instructions or ""
    assert "Nothing deletes a page: deletes go to a trash." in text
    assert ok(store, "read", page=page)["page"]["purge_at"] is None


def test_a_failure_after_the_purge_leaves_its_files_for_the_next_run(client, store):
    """Retention commits before any file is unlinked: a run that stops between the
    two has purged the page and deleted nothing; the next run deletes its files."""
    ref, sha = photo(client)
    trash(client, store, ref["page_id"])
    age_files(store)

    def stop():
        raise RuntimeError("stopped")
        yield

    with pytest.raises(RuntimeError):
        gc.collect(store, delete=True, _between=stop())
    assert store.trash(10) == []  # the purge was committed
    assert store.blob_path(sha).is_file()  # no file went with it
    with store.connect() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    report = gc.collect(store, delete=True)
    assert report.purged == 0 and sha in report.shas
    assert not store.blob_path(sha).exists()


def test_a_conflicted_gathering_leaves_review_pages_for_the_next_run(
    client, store, note, monkeypatch
):
    _, sha = unembed(client, store)
    gc.collect(store, delete=True)
    [page] = orphan_pages(client)
    trash(client, store, page["id"])
    other = note("Plain")
    trash(client, store, other["page_id"])
    age(store)

    def conflict(*args):
        raise ConflictError("edited meanwhile")

    monkeypatch.setattr(orphans, "gather", conflict)
    report = gc.collect(store, delete=True)
    assert (report.purged, report.let_go) == (1, 0)
    assert [r["id"] for r in store.trash(10)] == [page["id"]]
    assert store.blob_path(sha).is_file()
    monkeypatch.undo()
    monkeypatch.setattr(orphans, "clock", lambda: OCT)
    assert gc.collect(store, delete=True).let_go == 1


def test_the_trash_purge_can_be_off(client, store, capsys):
    ref, _ = photo(client)
    trash(client, store, ref["page_id"])
    main(["gc", "--data-dir", str(store.dir), "--delete", "--trash-days", "off"])
    assert "the trash is never purged (--trash-days off)" in capsys.readouterr().out
    assert len(store.trash(10)) == 1
    main(["gc", "--data-dir", str(store.dir), "--report", "--trash-days", "OFF"])
    assert "never purged (--trash-days off)" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args", [["--trash-days", "36501"], ["--job-days", "1e400"], ["--run-days", "inf"]]
)
def test_retention_has_a_ceiling(store, args):
    with pytest.raises(SystemExit, match="retention must be at most 36500 days"):
        main(["gc", "--data-dir", str(store.dir), *args])


def test_a_trash_setting_past_the_ceiling_stops_the_start(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_TRASH_DAYS", "36501")
    with pytest.raises(SystemExit, match=r"1 to 36500"):
        create_app(tmp_path / "data")
    monkeypatch.setenv("SCRAP_TRASH_DAYS", "36500")
    create_app(tmp_path / "data")


def test_the_report_counts_files_a_review_page_purge_frees(client, store, capsys):
    _, sha = unembed(client, store)
    gc.collect(store, delete=True)
    [page] = orphan_pages(client)
    trash(client, store, page["id"], now())
    r = sizes.measure(store)
    assert r["files"]["review_only"] == {"files": 1, "bytes": len(b"photo bytes")}
    assert r["trash"]["oldest_days"] == 0.0
    tables = {t["table"] for t in r["tables"]}
    assert tables & {"sqlite_schema", "sqlite_master"}
    main(["gc", "--data-dir", str(store.dir), "--report"])
    out = capsys.readouterr().out
    assert "the oldest 0.0 days" in out and "shown only on Orphaned assets" in out
    assert "not topic_run" in out
