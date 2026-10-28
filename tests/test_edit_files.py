# pyright: reportOptionalSubscript=false
"""Files sent with a page's edit (the page editor's Camera, Gallery and File):
PATCH /api/pages/{key} as multipart, each token in the body placed (helpers.placed)."""

import io
import json
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from scrap.app import create_app
from scrap.store import (
    ConflictError,
    Store,
    connect,
    new_ulid,
    now,
    topics,
    transaction,
)


def jpeg(colour="red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), colour).save(out, "JPEG")
    return out.getvalue()


PDF = b"%PDF-1.4 minutes"


def page_of(client, text="Trip notes\n\nday one"):
    ref = client.post("/api/captures", json={"id": new_ulid(), "text": text}).json()
    return client.get(f"/api/pages/{ref['page_id']}").json()


def patch(client, key, edit, *files):
    return client.patch(
        f"/api/pages/{key}",
        data={"edit": json.dumps(edit)},
        files=[("file", f) for f in files],
    )


def blob_rows(tmp_path):
    with closing(connect(tmp_path / "data" / "scrap.db")) as conn:
        return {r[0] for r in conn.execute("SELECT sha256 FROM blob")}


def test_files_are_placed_where_their_tokens_are_as_one_revision(client):
    p = page_of(client)
    body = "Trip notes\n\n⟦image 1⟧\n\nthe minutes: ⟦file 2⟧ and more\n\nend"
    r = patch(
        client, p["id"], {"base_rev": p["rev"], "body": body},
        ("board.jpg", jpeg(), "image/jpeg"),
        ("minutes [v2].pdf", PDF, "application/pdf"),
    )  # fmt: skip
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["rev"] == p["rev"] + 1
    new = saved["captures"][-1]
    assert new["kind"] == "photo"  # an image among them: read as Add photo's are
    img, doc = (b["sha256"] for b in new["blobs"])
    assert saved["body"] == (
        f"Trip notes\n\n![](/api/blobs/{img}/preview?size=2048)\n\n"
        f"the minutes: [minutes v2.pdf](/api/blobs/{doc}) and more\n\nend"
    )
    assert [b["filename"] for b in new["blobs"]] == ["board.jpg", "minutes [v2].pdf"]
    # The file's name is searchable, as the link's text
    hits = client.get("/api/search", params={"q": "minutes"}).json()
    assert [h["id"] for h in hits] == [p["id"]]


def test_files_alone_are_a_file_capture_read_for_search(client, tmp_path):
    p = page_of(client)
    body = f"{p['body']}\n\n⟦file 1: notes.md⟧"
    r = patch(
        client, p["id"], {"base_rev": p["rev"], "body": body},
        ("notes.md", b"# Notes\nwombat", ""),
    )  # fmt: skip
    assert r.status_code == 200, r.text
    new = r.json()["captures"][-1]
    assert new["kind"] == "file"
    sha = new["blobs"][0]["sha256"]
    assert r.json()["body"].endswith(f"[notes.md](/api/blobs/{sha})")
    with closing(connect(tmp_path / "data" / "scrap.db")) as conn:
        jobs = conn.execute(
            "SELECT count(*) FROM job WHERE source_sha256 = ?", (sha,)
        ).fetchone()[0]
    assert jobs == 1  # its text is read, as any capture's file


def test_a_stale_edit_stores_no_file(client, tmp_path):
    p = page_of(client)
    ok = client.patch(
        f"/api/pages/{p['id']}", json={"base_rev": p["rev"], "body": "changed"}
    )
    assert ok.status_code == 200
    before = blob_rows(tmp_path)
    r = patch(
        client, p["id"], {"base_rev": p["rev"], "body": "mine ⟦file 1⟧"},
        ("a.pdf", PDF, "application/pdf"),
    )  # fmt: skip
    assert r.status_code == 409
    assert r.json()["rev"] == p["rev"] + 1
    assert blob_rows(tmp_path) == before
    files = [f for f in (tmp_path / "data" / "files").rglob("*") if f.is_file()]
    assert files == []  # checked before any file was written
    assert len(client.get(f"/api/pages/{p['id']}").json()["captures"]) == 1


def test_an_edit_gone_stale_while_its_files_were_written_records_none(client, tmp_path):
    """The transaction's own check: the files are on disk but recorded nowhere, so
    gc deletes them after its grace period."""
    store = Store(tmp_path / "data")
    p = page_of(client)
    sha, size = store.put_blob(io.BytesIO(PDF))
    with pytest.raises(ConflictError):
        store.update_page(
            p["id"], p["rev"] - 1, None, "x ⟦file 1⟧", "me",
            uploads=[(sha, "application/pdf", size, "a.pdf")],
        )  # fmt: skip
    page = client.get(f"/api/pages/{p['id']}").json()
    assert len(page["captures"]) == 1 and page["rev"] == p["rev"]
    with store.connect() as conn:
        assert (
            conn.execute("SELECT 1 FROM blob WHERE sha256 = ?", (sha,)).fetchone()
            is None
        )


def test_refusals(client):
    p = page_of(client)
    edit = {"base_rev": p["rev"], "body": "x ⟦file 1⟧"}
    exe = ("a.exe", b"MZ", "application/x-msdownload")
    assert patch(client, p["id"], edit, exe).status_code == 415
    pdf = ("a.pdf", PDF, "application/pdf")
    assert patch(client, p["id"], {"title": "t"}, pdf).status_code == 422  # no body
    no_edit = client.patch(f"/api/pages/{p['id']}", files=[("file", pdf)])
    assert no_edit.status_code == 422
    bad = client.patch(
        f"/api/pages/{p['id']}", data={"edit": "{"}, files=[("file", pdf)]
    )
    assert bad.status_code == 422
    assert bad.json()["detail"][0]["loc"][0] == "edit"
    wrong = patch(client, p["id"], {"base_rev": "one", "body": "x"}, pdf)
    assert wrong.status_code == 422
    assert wrong.json()["detail"][0]["loc"] == ["edit", "base_rev"]
    assert len(client.get(f"/api/pages/{p['id']}").json()["captures"]) == 1


def test_json_edits_are_checked_as_before(client):
    p = page_of(client)
    r = client.patch(
        f"/api/pages/{p['id']}",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422
    r = client.patch(f"/api/pages/{p['id']}", json={"base_rev": "x", "body": "y"})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "base_rev"]
    r = client.patch(f"/api/pages/{p['id']}", json={"body": "y"})
    assert r.status_code == 422  # base_rev is needed
    r = client.patch(f"/api/pages/{p['id']}", json={"tags": ["a"]})
    assert r.status_code == 200 and r.json()["tags"] == ["a"]


def test_an_edit_over_the_upload_limit_is_413_and_stores_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_MAX_UPLOAD_MB", "0.001")  # 1048 bytes
    client = TestClient(create_app(tmp_path))
    p = page_of(client)
    big = ("big.pdf", b"%PDF-1.4 " + b"x" * 4096, "application/pdf")
    r = patch(client, p["id"], {"base_rev": p["rev"], "body": "x ⟦file 1⟧"}, big)
    assert r.status_code == 413
    assert r.json()["detail"].endswith("MB upload limit")
    page = client.get(f"/api/pages/{p['id']}").json()
    assert (page["rev"], len(page["captures"])) == (p["rev"], 1)
    assert not [f for f in (tmp_path / "files").rglob("*") if f.is_file()]


def test_a_topic_page_takes_no_files_with_its_edit(client, tmp_path):
    store = Store(tmp_path / "data")
    with closing(connect(store.db)) as conn, transaction(conn):
        page_id = topics.create(conn, "Queues", "queues", "queues", "me", now())
    edit = {"base_rev": 1, "body": "x ⟦file 1⟧"}
    r = patch(client, "queues", edit, ("a.pdf", PDF, "application/pdf"))
    assert r.status_code == 422
    assert r.json()["detail"] == "Files can't be added to a topic page"
    page = client.get(f"/api/pages/{page_id}").json()
    assert (page["rev"], page["captures"]) == (1, [])
