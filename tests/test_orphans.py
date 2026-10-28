"""scrap gc gathers orphaned files onto a monthly review page (#124)."""

import hashlib
import os
import time
import urllib.request
from datetime import UTC, datetime
from io import BytesIO

import pytest

from scrap import gc, orphans
from scrap.__main__ import main
from scrap.store import Store, new_ulid

DAY = 24 * 3600
OCT = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
LATER_OCT = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
NOV = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


@pytest.fixture
def store(client, tmp_path, monkeypatch):
    monkeypatch.setattr(orphans, "clock", lambda: OCT)
    monkeypatch.delenv("SCRAP_NOTIFY_URL", raising=False)
    return Store(tmp_path / "data")


def photo(client, data=b"photo bytes", text="A photo"):
    r = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": text},
        files=[("file", ("p.png", data, "image/png"))],
    )
    assert r.status_code == 201, r.text
    return r.json(), hashlib.sha256(data).hexdigest()


def edit(client, key, body):
    """Save a new text on a page (by id or slug); returns the page."""
    page = client.get(f"/api/pages/{key}").json()
    r = client.patch(f"/api/pages/{key}", json={"base_rev": page["rev"], "body": body})
    assert r.status_code == 200, r.text
    return r.json()


def age(store, days=2):
    """Every revision so far, and every file, days older: past the grace period,
    the revisions still in their order."""
    with store.connect() as conn:
        conn.execute(
            "UPDATE page_rev SET created_at ="
            " strftime('%Y-%m-%dT%H:%M:%fZ', created_at, ?)",
            (f"-{days} days",),
        )
    for path in store.files.rglob("*"):
        if path.is_file():
            t = time.time() - days * DAY
            os.utime(path, (t, t))


def unembed(client, store, text="A photo", data=b"photo bytes"):
    """A photo page whose embed was deleted two days ago: an orphan."""
    ref, sha = photo(client, data, text)
    edit(client, ref["page_id"], text)
    age(store)
    return ref, sha


def orphan_pages(client):
    return [
        p
        for p in client.get("/api/pages?limit=500").json()
        if p["title"].startswith("Orphaned assets")
    ]


def describe(store, cid, sha, text):
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO derived (capture_id, source_sha256, kind, version, producer,"
            " text, data, created_at) VALUES (?, ?, 'description', 1, 'model', ?,"
            " '{}', '2026-10-01T00:00:00.000Z')",
            (cid, sha, text),
        )


def test_an_orphan_goes_on_a_todo_page_once(client, store):
    ref, sha = unembed(client, store)
    describe(store, ref["capture_id"], sha, "A cat\non a mat")
    report = gc.collect(store, delete=True)
    assert report.orphans == 1 and sha not in report.shas
    assert "gathered 1 orphaned files onto Orphaned assets 2026-10" in report.text()
    [row] = orphan_pages(client)
    page = client.get(f"/api/pages/{row['id']}").json()
    assert page["title"] == "Orphaned assets 2026-10"
    assert page["kind"] == "todo" and page["fields"]["status"] == "open"
    assert page["due"] == "2026-10-31"  # a firm 7 days after it was made
    assert f"![](/api/blobs/{sha}/preview?size=2048)" in page["body"]
    slug = client.get(f"/api/pages/{ref['page_id']}").json()["slug"]
    assert f"From [[{slug}|A photo]], last shown" in page["body"]
    assert "> A cat\n> on a mat" in page["body"]
    assert page["captures"][0]["source"] == "gc"  # the user's page, not Claude's
    assert page["captures"][0]["blobs"] == []
    with store.connect() as conn:  # not read by Claude's enrichment
        assert not conn.execute("SELECT 1 FROM enrich_job").fetchall()
    assert store.blob_path(sha).is_file()

    again = gc.collect(store, delete=True)  # nothing twice
    assert again.orphans == 0
    assert client.get(f"/api/pages/{row['id']}").json() == page
    assert len(orphan_pages(client)) == 1


def test_a_file_the_page_stopped_showing_is_hidden_but_still_gathered(client, store):
    """#303: the capture keeps it, so gc protects it and gathers it as an orphan."""
    ref, sha = unembed(client, store)
    [row] = client.get("/api/pages").json()
    assert row["thumb"] is None and store.images_of([ref["page_id"]]) == {}
    with store.connect() as conn:
        assert sha in gc.in_use(conn)
    report = gc.collect(store, delete=True)
    assert report.orphans == 1 and sha not in report.shas
    assert store.blob_path(sha).is_file()


def test_a_dry_run_counts_and_writes_nothing(client, store, capsys):
    unembed(client, store)
    report = gc.collect(store)
    assert report.orphans == 1 and "would gather 1 orphaned files" in report.text()
    main(["gc", "--data-dir", str(store.dir)])
    assert "would gather 1 orphaned files" in capsys.readouterr().out
    assert orphan_pages(client) == []


def test_a_file_cut_just_now_is_left_for_the_next_run(client, store):
    """A line cut and pasted back a minute later is not gathered meanwhile."""
    ref, sha = photo(client)
    edit(client, ref["page_id"], "A photo")
    assert gc.collect(store, delete=True).orphans == 0
    assert orphan_pages(client) == []


def test_later_orphans_append_and_a_new_month_starts_a_page(client, store, monkeypatch):
    unembed(client, store, "First", b"first")
    gc.collect(store, delete=True)
    [first] = orphan_pages(client)

    monkeypatch.setattr(orphans, "clock", lambda: LATER_OCT)
    _, sha = unembed(client, store, "Second", b"second")
    assert gc.collect(store, delete=True).orphans == 1
    [same] = orphan_pages(client)
    assert same["id"] == first["id"] and same["due"] == first["due"] == "2026-10-31"
    assert f"/api/blobs/{sha}/" in client.get(f"/api/pages/{same['id']}").json()["body"]

    monkeypatch.setattr(orphans, "clock", lambda: NOV)
    _, sha = unembed(client, store, "Third", b"third")
    gc.collect(store, delete=True)
    pages = {p["title"]: p for p in orphan_pages(client)}
    assert set(pages) == {"Orphaned assets 2026-10", "Orphaned assets 2026-11"}
    assert pages["Orphaned assets 2026-11"]["due"] == "2026-11-09"
    new = client.get(f"/api/pages/{pages['Orphaned assets 2026-11']['id']}").json()
    assert f"/api/blobs/{sha}/" in new["body"] and "First" not in new["body"]


def test_a_page_ticked_done_is_reviewed(client, store):
    unembed(client, store, "First", b"first")
    gc.collect(store, delete=True)
    [first] = orphan_pages(client)
    client.patch(
        f"/api/pages/{first['id']}", json={"fields": {"status": "done"}}
    ).raise_for_status()
    unembed(client, store, "Second", b"second")
    gc.collect(store, delete=True)
    pages = orphan_pages(client)
    assert len(pages) == 2 and {p["title"] for p in pages} == {first["title"]}


def test_a_file_still_used_elsewhere_is_not_an_orphan(client, store):
    # Shown by a page in the trash
    ref, sha = photo(client, b"trashed use")
    other, _ = photo(client, b"other", "Other")
    edit(client, other["page_id"], f"![](/api/blobs/{sha}/preview?size=2048)")
    client.delete(f"/api/pages/{other['page_id']}").raise_for_status()
    edit(client, ref["page_id"], "gone here")
    # Its capture's page is in the trash
    gone, _ = photo(client, b"in the trash", "Trashed")
    edit(client, gone["page_id"], "Trashed")
    client.delete(f"/api/pages/{gone['page_id']}").raise_for_status()
    # Held by another capture whose page lists it (made before photos were embedded)
    a, both = photo(client, b"twice", "Embedded")
    b, _ = photo(client, b"twice", "Listed")
    with store.connect() as conn:
        conn.execute("UPDATE page SET body = 'Listed' WHERE id = ?", (b["page_id"],))
        conn.execute(
            "UPDATE page_rev SET body = 'Listed' WHERE page_id = ?", (b["page_id"],)
        )
    edit(client, a["page_id"], "Embedded")
    # A PDF, listed below its page and never embedded
    r = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "A PDF"},
        files=[("file", ("a.pdf", b"%PDF-1.4", "application/pdf"))],
    )
    edit(client, r.json()["page_id"], "A PDF, edited")
    age(store)
    report = gc.collect(store, delete=True)
    assert report.orphans == 0 and orphan_pages(client) == []


def test_a_deleted_page_keeps_its_files_in_the_trash_and_gathers_none_again(
    client, store
):
    """Deleting the page is the review: its files stay with it in the trash (nothing is
    purged from the trash), never gathered again and never deleted by gc."""
    _, sha = unembed(client, store)
    gc.collect(store, delete=True)
    [page] = orphan_pages(client)
    client.delete(f"/api/pages/{page['id']}").raise_for_status()
    age(store)
    report = gc.collect(store, delete=True, grace_hours=0)
    assert report.orphans == 0 and sha not in report.shas
    assert orphan_pages(client) == [] and store.blob_path(sha).is_file()
    client.post(f"/api/pages/{page['id']}/undelete").raise_for_status()
    assert f"/api/blobs/{sha}/" in client.get(f"/api/pages/{page['id']}").json()["body"]


def test_cutting_an_item_into_another_page_adopts_it(client, store, note):
    _, sha = unembed(client, store)
    gc.collect(store, delete=True)
    [page] = orphan_pages(client)
    body = client.get(f"/api/pages/{page['id']}").json()["body"]
    item = f"![](/api/blobs/{sha}/preview?size=2048)"
    edit(client, page["id"], body.replace(item, ""))
    home = note("New home")
    edit(client, home["page_id"], f"New home\n\n{item}")
    age(store)
    assert gc.collect(store, delete=True).orphans == 0
    assert item not in client.get(f"/api/pages/{page['id']}").json()["body"]
    # Deleted from its new page later: an orphan again
    edit(client, home["page_id"], "New home")
    age(store)
    assert gc.collect(store, delete=True).orphans == 1
    assert item in client.get(f"/api/pages/{page['id']}").json()["body"]


def test_an_item_cut_from_the_page_and_dropped_is_reviewed(client, store):
    _, sha = unembed(client, store)
    gc.collect(store, delete=True)
    [page] = orphan_pages(client)
    edit(client, page["id"], "Looked through")
    age(store)
    assert gc.collect(store, delete=True).orphans == 0
    assert client.get(f"/api/pages/{page['id']}").json()["body"] == "Looked through"


def test_delete_keeps_a_file_only_the_orphan_page_shows(client, store):
    """gc --delete no longer deletes orphans: once gathered, a file the review page
    shows is in use even with no capture left."""
    ref, sha = unembed(client, store)
    gc.collect(store, delete=True)
    with store.connect() as conn:
        conn.execute("DELETE FROM capture WHERE id = ?", (ref["capture_id"],))
    report = gc.collect(store, delete=True, grace_hours=0)
    assert sha not in report.shas and store.blob_path(sha).is_file()


def test_a_file_that_is_not_an_image_is_linked(client, store):
    r = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "A PDF"},
        files=[("file", ("a [draft].pdf", b"%PDF-1.4", "application/pdf"))],
    )
    sha = hashlib.sha256(b"%PDF-1.4").hexdigest()
    ref = r.json()
    edit(client, ref["page_id"], f"A PDF [read](/api/blobs/{sha})")
    edit(client, ref["page_id"], "A PDF")
    age(store)
    assert gc.collect(store, delete=True).orphans == 1
    [page] = orphan_pages(client)
    body = client.get(f"/api/pages/{page['id']}").json()["body"]
    assert f"[a draft .pdf](/api/blobs/{sha})" in body


def test_a_file_placed_by_its_capture_and_unlinked_later_is_gathered(client, store):
    """#403: a PDF the composer placed in the text (its link, by a token) and later
    deleted from it is an orphan, as an image whose embed was deleted (#303)."""
    r = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "Minutes ⟦file 1⟧", "place": "1"},
        files=[("file", ("m.pdf", b"%PDF-1.4 placed", "application/pdf"))],
    )
    sha = hashlib.sha256(b"%PDF-1.4 placed").hexdigest()
    ref = r.json()
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert page["body"] == f"Minutes [m.pdf](/api/blobs/{sha})"
    assert edit(client, ref["page_id"], "Minutes")["removed"] == [sha]
    age(store)
    assert gc.collect(store, delete=True).orphans == 1
    [row] = orphan_pages(client)
    body = client.get(f"/api/pages/{row['id']}").json()["body"]
    assert f"[m.pdf](/api/blobs/{sha})" in body
    assert store.blob_path(sha).is_file()


def test_a_full_page_continues_on_a_new_one(client, store, monkeypatch):
    unembed(client, store, "First", b"first")
    gc.collect(store, delete=True)
    [first] = orphan_pages(client)
    size = len(client.get(f"/api/pages/{first['id']}").json()["body"].encode())
    monkeypatch.setattr(orphans, "MAX_PAGE", size + 10)
    unembed(client, store, "Second", b"second")
    unembed(client, store, "Third", b"third")
    assert gc.collect(store, delete=True).orphans == 2
    pages = orphan_pages(client)
    assert len(pages) == 3  # one item each: none fits beside another


def test_a_new_page_is_announced_once(client, store, monkeypatch):
    sent: list[tuple[str, bytes]] = []

    class Done:
        def close(self):
            pass

    def urlopen(url, data, timeout):
        sent.append((url, data))
        return Done()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("SCRAP_NOTIFY_URL", "https://ntfy.example/scrap")
    unembed(client, store, "First", b"first")
    gc.collect(store, delete=True)
    unembed(client, store, "Second", b"second")
    gc.collect(store, delete=True)  # appended: no second notice
    assert sent == [
        (
            "https://ntfy.example/scrap",
            b"scrap gc gathered orphaned files onto Orphaned assets 2026-10."
            b" Review it in scrap.",
        )
    ]

    def fails(url, data, timeout):
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", fails)
    monkeypatch.setattr(orphans, "clock", lambda: NOV)
    unembed(client, store, "Third", b"third")
    assert gc.collect(store, delete=True).orphans == 1  # a lost notice is not an error


def test_an_orphan_page_edited_meanwhile_skips_only_the_gathering(
    client, store, monkeypatch, caplog
):
    """A conflict on the review page is not a failed run: the delete and prune
    phases still run, and the next run gathers what this one could not."""
    unembed(client, store, "First", b"first")
    gc.collect(store, delete=True)
    _, sha = unembed(client, store, "Second", b"second")
    unused, _ = store.put_blob(BytesIO(b"nobody's"))
    age(store)
    real = orphans._current

    def stale(conn, month):
        found = real(conn, month)
        return found and (found[0], found[1] - 1, found[2])

    monkeypatch.setattr(orphans, "_current", stale)
    report = gc.collect(store, delete=True)
    assert report.orphans == 0 and report.deleted
    assert unused in report.shas and not store.blob_path(unused).exists()
    assert "orphan page changed meanwhile" in caplog.text
    monkeypatch.setattr(orphans, "_current", real)
    assert gc.collect(store, delete=True).orphans == 1


def test_a_review_page_is_known_by_its_capture_not_its_title(client, store, note):
    """Renamed, it is still the month's page (and items cut from it stay reviewed);
    a todo of the user's with the same title is never written to."""
    mine = note("Orphaned assets 2026-10", kind="todo")
    _, first = unembed(client, store, "First", b"first")
    gc.collect(store, delete=True)
    [review] = [p for p in orphan_pages(client) if p["id"] != mine["page_id"]]
    page = client.get(f"/api/pages/{review['id']}").json()
    client.patch(
        f"/api/pages/{review['id']}",
        json={"base_rev": page["rev"], "title": "Photos to sort", "body": "Sorted"},
    ).raise_for_status()
    _, second = unembed(client, store, "Second", b"second")
    assert gc.collect(store, delete=True).orphans == 1  # not First: reviewed
    body = client.get(f"/api/pages/{review['id']}").json()["body"]
    assert f"/api/blobs/{second}/" in body and f"/api/blobs/{first}/" not in body
    untouched = client.get(f"/api/pages/{mine['page_id']}").json()
    assert untouched["rev"] == 1 and "/api/blobs/" not in untouched["body"]
