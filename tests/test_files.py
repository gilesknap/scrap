# pyright: reportOptionalSubscript=false
"""A file's text, read locally for search (#234): PDFs and text files, no model."""

import io
import json
import resource
import subprocess
import sys
import zlib
from contextlib import closing
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from scrap import claude, ingest
from scrap.app import create_app
from scrap.ingest import FAR, files, pdftext
from scrap.store import Store, connect, new_ulid
from test_mcp import ok


def pdf(*pages: str) -> bytes:
    """A PDF with a page of Helvetica text for each string ('' : a page with none, as a
    scan's has)."""
    return build(
        [f"BT /F1 12 Tf 72 720 Td ({t}) Tj ET".encode() if t else b"" for t in pages]
    )


def build(contents: list[bytes], flate: bool = False) -> bytes:
    """A PDF with a page for each content stream (already deflated, with flate)."""
    n = len(contents)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    filtered = b" /Filter /FlateDecode" if flate else b""
    for i, content in enumerate(contents):
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            b" /Resources << /Font << /F1 3 0 R >> >>"
            b" /Contents %d 0 R >>" % (5 + 2 * i)
        )
        objs.append(
            b"<< /Length %d%s >>\nstream\n%s\nendstream"
            % (len(content), filtered, content)
        )
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref,
    )
    return out


def deflated(unit: bytes, mb: int) -> bytes:
    """unit repeated to about mb MB, deflated (fast: level 1)."""
    co = zlib.compressobj(1)
    chunk = unit * (2**20 // len(unit))
    return b"".join(co.compress(chunk) for _ in range(mb)) + co.flush()


def encrypted(data: bytes, password: str) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    writer.encrypt(user_password=password, owner_password="owner")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    store.migrate()
    return store


@pytest.fixture
def conn(store):
    with closing(connect(store.db)) as conn:
        yield conn


def attach(store, data: bytes, mime="application/pdf", name="f.pdf", text=None):
    """Capture a file (with a note's text, if given); its reference."""
    sha, size = store.put_blob(io.BytesIO(data))
    c = store.prepare({"id": new_ulid(), "text": text}, [mime])
    return store.capture(c, [(sha, mime, size, name)], "me")[0]


class NoCall:
    """Claude, which a file's job must never call."""

    def __call__(self, *args: Any, **kw: Any) -> claude.Completion:
        raise AssertionError("a file's job called Claude")


def run(store) -> bool:
    return ingest.Worker(store, NoCall()).step()


def job(conn) -> tuple[str, int, str | None]:
    row = conn.execute("SELECT state, failures, last_error FROM job").fetchone()
    return row[0], row[1], row[2]


def blob(store, ref) -> dict[str, Any]:
    return store.page(ref["page_id"])["captures"][0]["blobs"][0]


# ---- the reader


def test_the_child_reads_pages_and_cuts_at_its_limits(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(pdf("alpha one", "beta two", "gamma three"))
    got = files.read_pdf(path)
    assert (got["pages"], got["pages_read"], got["truncated"]) == (3, 3, False)
    assert got["text"].split() == ["alpha", "one", "beta", "two", "gamma", "three"]
    out = pdftext.extract(str(path), 2, 1000)  # in process: no memory cap here
    assert (out["pages"], out["pages_read"], out["truncated"]) == (3, 2, True)
    assert "gamma" not in out["text"]
    out = pdftext.extract(str(path), 200, 12)
    assert out["text"] == "alpha one\nbe" and out["truncated"]


def test_page_and_character_caps_are_patchable(tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.write_bytes(pdf(*[f"page{i}" for i in range(5)]))
    monkeypatch.setattr(files, "MAX_PAGES", 2)
    got = files.read_pdf(path)
    assert (got["pages"], got["pages_read"], got["truncated"]) == (5, 2, True)
    assert got["text"].split() == ["page0", "page1"]
    monkeypatch.setattr(files, "MAX_PAGES", 200)
    monkeypatch.setattr(files, "MAX_CHARS", 8)
    got = files.read_pdf(path)
    assert got["text"] == "page0\npa" and got["truncated"]


def test_an_empty_password_is_tried_and_any_other_refused(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(encrypted(pdf("open sesame"), ""))
    assert files.read_pdf(path)["text"] == "open sesame"
    path.write_bytes(encrypted(pdf("hidden words"), "secret"))
    with pytest.raises(files.FileError, match="needs a password"):
        files.read_pdf(path)


def test_the_child_reports_running_out_of_memory(tmp_path, monkeypatch):
    def boom(*args: Any) -> dict[str, Any]:
        raise MemoryError

    monkeypatch.setattr(pdftext, "limit", lambda memory, cpu: None)
    monkeypatch.setattr(pdftext, "extract", boom)
    # main() turns logging off for the child: not for this test process (caplog)
    monkeypatch.setattr(pdftext.logging, "disable", lambda level: None)
    assert pdftext.main(["x.pdf", "1", "1", "1", "1"]) == pdftext.OUT_OF_MEMORY
    monkeypatch.setattr(files, "COMMAND", [sys.executable, "-c", "exit(3)"])
    with pytest.raises(files.FileError, match="memory: reading the PDF needed over"):
        files.read_pdf(tmp_path / "x.pdf")


def test_the_memory_cap_stops_a_pdf_of_many_operators(tmp_path, monkeypatch):
    """60 MB of text operators on a page, deflated to under 0.5 MB: over a 150 MB cap
    the child stops, and says it was memory."""
    path = tmp_path / "ops.pdf"
    ops = deflated(b"BT /F1 12 Tf 72 720 Td (ab) Tj ET\n", 60)
    path.write_bytes(build([ops], flate=True))
    monkeypatch.setattr(files, "MEMORY", 150 * 2**20)
    with pytest.raises(files.FileError, match="^memory: reading the PDF needed over"):
        files.read_pdf(path)


def test_a_decompression_bomb_is_refused(tmp_path):
    path = tmp_path / "bomb.pdf"
    path.write_bytes(build([deflated(bytes(1024), 80)], flate=True))  # 80 MB of 0
    with pytest.raises(files.FileError, match="^content: the PDF could not be read$"):
        files.read_pdf(path)


def test_a_flood_of_warnings_never_reaches_the_service(tmp_path, monkeypatch):
    """A page of a hundred thousand draws of an image it does not have: pypdf warns
    for each. The child's stderr is discarded, never piped to the service (which would
    hold it all in memory), and it gets none of the service's environment."""
    path = tmp_path / "warns.pdf"
    path.write_bytes(build([deflated(b"/Im9 Do\n", 1)], flate=True))
    seen: dict[str, Any] = {}
    real = subprocess.run

    def spy(*args: Any, **kw: Any) -> subprocess.CompletedProcess[bytes]:
        seen.update(kw)
        return real(*args, **kw)

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secret")
    monkeypatch.setattr(files.subprocess, "run", spy)
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert files.read_pdf(path)["text"] == ""
    assert seen["stderr"] is subprocess.DEVNULL and "capture_output" not in seen
    assert seen["env"] == files.ENV and "CLAUDE_CODE_OAUTH_TOKEN" not in seen["env"]
    grown = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
    assert grown < 50 * 1024  # KiB: not the warnings


def test_the_child_sees_no_environment(tmp_path, monkeypatch):
    out = tmp_path / "env.json"
    code = f"import json, os; json.dump(dict(os.environ), open({str(out)!r}, 'w'))"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setattr(files, "COMMAND", [sys.executable, "-c", code])
    with pytest.raises(files.FileError):  # it prints no answer
        files.read_pdf(tmp_path / "x.pdf")
    assert "ANTHROPIC_API_KEY" not in json.loads(out.read_text())


# ---- the worker


def test_a_text_pdf_is_read_indexed_and_shown_with_no_model(store, conn):
    ref = attach(store, pdf("cover page", "contents", "the zanzibar clause"))
    assert job(conn)[0] == "queued"
    assert blob(store, ref)["ingest"]["state"] == "queued"
    assert store.search("zanzibar", 10) == []
    assert run(store) is True
    assert job(conn) == ("done", 0, None)
    row = conn.execute("SELECT * FROM derived").fetchone()
    assert (row["kind"], row["run_id"]) == ("ocr", None)
    assert row["producer"].startswith("pypdf ")
    assert json.loads(row["data"]) == {
        "kind": "pdf", "pages": 3, "pages_read": 3, "truncated": False,
    }  # fmt: skip
    assert conn.execute("SELECT count(*) FROM model_run").fetchone()[0] == 0
    hits = store.search("zanzibar", 10)
    assert [h["id"] for h in hits] == [ref["page_id"]]
    assert "zanzibar" in hits[0]["snippet"]
    assert store.search("zanzibar kind:note", 10)  # filters still apply
    assert store.search("zanzibar has:image", 10) == []
    got = blob(store, ref)["ingest"]
    assert got == {
        "state": "done", "failures": 0, "error": None, "kind": "pdf", "pages": 3,
        "pages_read": 3, "truncated": False, "text_chars": len(row["text"]),
        "searchable": True,
    }  # fmt: skip
    page = store.page(ref["page_id"])
    assert page["body"] == "" and page["tags"] == []  # nothing from the file
    assert conn.execute("SELECT count(*) FROM enrich_job").fetchone()[0] == 0
    file = ok(store, "read", page=ref["slug"])["files"][0]
    assert (file["state"], file["pages"], file["searchable"]) == ("done", 3, True)
    assert "zanzibar clause" in file["text"] and file["text_truncated"] is False
    assert file["description"] is None


def test_read_caps_a_files_text(store, monkeypatch):
    import scrap.mcp_tools.reading as reading

    ref = attach(store, pdf("word " * 50))
    run(store)
    monkeypatch.setattr(reading, "MAX_FILE_TEXT", 20)
    file = ok(store, "read", page=ref["slug"])["files"][0]
    assert file["text"] == "word word word word " and file["text_truncated"]


def test_a_scan_with_no_text_is_done_but_not_searchable(store, conn):
    ref = attach(store, pdf("", ""))
    run(store)
    assert job(conn)[0] == "done"
    got = blob(store, ref)["ingest"]
    assert (got["state"], got["pages"], got["searchable"]) == ("done", 2, False)
    assert conn.execute("SELECT count(*) FROM chunk WHERE derived_id IS NOT NULL")
    file = ok(store, "read", page=ref["slug"])["files"][0]
    assert (file["searchable"], file["text"], file["pages"]) == (False, None, 2)


def test_a_corrupt_pdf_dies_at_once_and_stays_attached(store, conn):
    ref = attach(store, b"%PDF-1.4 this is not a pdf")
    run(store)
    assert job(conn) == ("dead", 1, "content: the PDF could not be read")
    got = blob(store, ref)["ingest"]
    assert (got["state"], got["error"]) == (
        "failed",
        "content: the PDF could not be read",
    )
    assert got["searchable"] is False
    assert len(store.page(ref["page_id"])["captures"][0]["blobs"]) == 1
    assert conn.execute("SELECT count(*) FROM enrich_job").fetchone()[0] == 0
    # Retry (Reprocess) queues it again
    assert ingest.reprocess(store, ref["capture_id"], None, False) == {
        "queued": 1, "already": 0,
    }  # fmt: skip
    assert conn.execute("SELECT count(*) FROM job WHERE state = 'queued'").fetchone()[0]


def test_an_oversized_file_is_refused_before_reading(store, conn, monkeypatch):
    monkeypatch.setattr(files, "MAX_FILE", 2**20)
    monkeypatch.setattr(files, "COMMAND", ["false"])  # never run
    attach(store, pdf("big") + b"%" * (2 * 2**20))
    run(store)
    assert job(conn) == ("dead", 1, "too large: 2 MB, over the 1 MB limit")


def test_a_reader_that_runs_too_long_is_killed(store, conn, monkeypatch):
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    monkeypatch.setattr(files, "COMMAND", sleeper)
    monkeypatch.setattr(files, "TIMEOUT", 0.5)
    attach(store, pdf("slow"))
    run(store)
    assert job(conn) == ("dead", 1, "timeout: reading the PDF took over 0.5 s")


@pytest.mark.parametrize(
    ("data", "mime", "name"),
    [
        (b"\xef\xbb\xbfthe quokka note\n", "text/plain", "n.txt"),  # a BOM
        (b"# Title\n\nthe quokka \xff note", "text/markdown", "n.md"),
        (b"the quokka note", "text/plain; charset=utf-8", "n.txt"),
    ],
)
def test_a_text_file_is_read_in_process(store, conn, monkeypatch, data, mime, name):
    monkeypatch.setattr(files, "COMMAND", ["false"])  # no child for text
    ref = attach(store, data, mime, name)
    run(store)
    assert job(conn)[0] == "done"
    row = conn.execute("SELECT text, producer, data FROM derived").fetchone()
    assert row["producer"] == "scrap" and not row["text"].startswith("﻿")
    assert json.loads(row["data"])["kind"] == "text"
    assert [h["id"] for h in store.search("quokka", 10)] == [ref["page_id"]]
    got = blob(store, ref)["ingest"]
    assert (got["kind"], got["pages"], got["searchable"]) == ("text", None, True)


def test_a_text_files_characters_are_capped(store, conn, monkeypatch):
    monkeypatch.setattr(files, "MAX_CHARS", 5)
    attach(store, b"abc\x02defgh", "text/plain", "n.txt")
    run(store)
    row = conn.execute("SELECT text, data FROM derived").fetchone()
    assert row["text"] == "abc d" and json.loads(row["data"])["truncated"]


# ---- the queue


def test_a_file_is_read_while_the_queue_is_paused_and_spends_nothing(
    store, conn, monkeypatch
):
    monkeypatch.setenv("SCRAP_BUDGET_DAY_USD", "0")  # over budget at once
    photo_sha, size = store.put_blob(io.BytesIO(b"jpeg"))
    c = store.prepare({"id": new_ulid()}, ["image/jpeg"])
    store.capture(c, [(photo_sha, "image/jpeg", size, None)], "me")
    ref = attach(store, pdf("paused but read"))
    conn.execute("UPDATE queue_state SET paused_until = ?, reason = 'credit'", (FAR,))
    assert blob(store, ref)["ingest"]["state"] == "queued"  # never paused
    assert run(store) is True  # the file, though the photo is older
    assert run(store) is False  # the photo waits for Resume
    states = dict(conn.execute(
        "SELECT b.mime, j.state FROM job j JOIN blob b ON b.sha256 = j.source_sha256"
    ).fetchall())  # fmt: skip
    assert states == {"image/jpeg": "queued", "application/pdf": "done"}
    assert conn.execute("SELECT count(*) FROM model_run").fetchone()[0] == 0
    q = conn.execute("SELECT paused_until, reason FROM queue_state").fetchone()
    assert tuple(q) == (FAR, "credit")  # a file's success does not end a pause


def test_a_files_job_queues_no_related_call(store, conn, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    attach(store, pdf("related never"))
    attach(store, b"%PDF broken")
    run(store)
    run(store)
    assert conn.execute("SELECT count(*) FROM enrich_job").fetchone()[0] == 0


def test_a_pdf_first_page_still_gets_its_photos_related_call(store, conn, monkeypatch):
    """A page made from a PDF with a photo added later: the photo capture is still
    the first photo capture, so reading it queues the page's first related call."""
    from test_ingest import SCENE, Fake, jpeg

    monkeypatch.setenv("SCRAP_INGEST", "on")
    client = TestClient(create_app(store.dir))
    ref = attach(store, pdf("first a pdf"))
    files_ = [("file", ("p.jpg", jpeg(), "image/jpeg"))]
    r = client.post(f"/api/pages/{ref['page_id']}/captures",
                    data={"id": new_ulid()}, files=files_)  # fmt: skip
    assert r.status_code == 201
    worker = ingest.Worker(store, Fake(SCENE))
    assert worker.step() and worker.step()  # the PDF, then the photo
    reasons = [r[0] for r in conn.execute("SELECT reason FROM enrich_job")]
    assert reasons == ["related"]


def test_a_waiting_pdf_does_not_hold_back_a_boards_write_up(store, conn, monkeypatch):
    from test_ingest import BOARD, Fake, jpeg

    monkeypatch.setenv("SCRAP_INGEST", "on")
    sha, size = store.put_blob(io.BytesIO(jpeg()))
    c = store.prepare({"id": new_ulid()}, ["image/jpeg"])
    ref = store.capture(c, [(sha, "image/jpeg", size, None)], "me")[0]
    client = TestClient(create_app(store.dir))
    r = add(client, ref["page_id"], ("m.pdf", pdf("x"), "application/pdf"))
    assert r.status_code == 201
    assert ingest.Worker(store, Fake(BOARD)).step()  # the photo; the PDF still waits
    assert conn.execute("SELECT count(*) FROM job WHERE state = 'queued'").fetchone()[0]
    reasons = [r[0] for r in conn.execute("SELECT reason FROM enrich_job")]
    assert reasons == ["writeup"]


def test_status_counts_file_jobs_with_the_photos(store):
    attach(store, pdf("counted"))
    assert ingest.status(store)["jobs"] == {"queued": 1}


# ---- adding a PDF to a page


def add(client, key, *parts: tuple[str, bytes, str]):
    files_ = [("file", part) for part in parts]
    return client.post(f"/api/pages/{key}/captures", data={"id": new_ulid()},
                       files=files_)  # fmt: skip


def test_a_pdf_added_to_a_page_is_listed_not_put_in_its_text(client, note):
    ref = note("Minutes\nof the meeting")
    r = add(client, ref["page_id"], ("m.pdf", pdf("agenda"), "application/pdf"))
    assert r.status_code == 201, r.text
    page = r.json()
    assert (page["rev"], page["appended_on"]) == (1, None)
    assert page["body"] == "Minutes\nof the meeting"
    added = page["captures"][1]
    assert added["kind"] == "file" and added["blobs"][0]["filename"] == "m.pdf"
    assert added["blobs"][0]["ingest"]["state"] == "queued"


def test_a_photo_and_a_pdf_together_make_a_photo_capture(client, note):
    from test_photos import jpeg

    ref = note("Both")
    r = add(client, ref["page_id"], ("a.jpg", jpeg(), "image/jpeg"),
            ("m.pdf", pdf("x"), "application/pdf"))  # fmt: skip
    page = r.json()
    assert (page["rev"], page["appended_on"]) == (2, 1)  # the image is embedded
    image, doc = page["captures"][1]["blobs"]
    assert page["captures"][1]["kind"] == "photo"
    assert image["ingest"]["state"] == "queued"  # sent to Claude, as Add photo's are
    assert doc["ingest"]["state"] == "queued" and doc["ingest"]["kind"] == "pdf"


def test_a_missing_file_kills_its_job_at_once(store, conn):
    ref = attach(store, pdf("gone"))
    sha = blob(store, ref)["sha256"]
    store.blob(sha)[0].unlink()
    run(store)
    assert job(conn) == ("dead", 1, "internal: NotFoundError")


def test_a_reader_that_cannot_start_kills_its_job_at_once(store, conn, monkeypatch):
    monkeypatch.setattr(files, "COMMAND", ["/no/such/python"])
    attach(store, pdf("x"))
    run(store)
    assert job(conn) == ("dead", 1, "internal: FileNotFoundError")


def test_an_untyped_md_file_is_typed_by_its_name(client):
    files_ = [("file", ("notes.md", b"the wombat", "application/octet-stream"))]
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files_).json()
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    got = page["captures"][0]["blobs"][0]
    assert got["mime"] == "text/markdown" and got["ingest"]["state"] == "queued"


def test_other_files_are_refused(client, note):
    ref = note("Zip")
    r = add(client, ref["page_id"], ("a.zip", b"PK\x03\x04", "application/zip"))
    assert r.status_code == 415
    assert "images and PDFs" in r.json()["detail"]
    r = add(client, ref["page_id"], ("n.txt", b"text", "text/plain"))
    assert r.status_code == 415  # a text file goes in as a capture of its own
    assert client.get(f"/api/pages/{ref['page_id']}").json()["rev"] == 1


def test_reprocess_requeues_a_failed_pdf_through_the_api(tmp_path):
    client = TestClient(create_app(tmp_path))
    files_ = [("file", ("bad.pdf", b"%PDF nonsense", "application/pdf"))]
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files_).json()
    store = Store(tmp_path)
    run(store)
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    got = page["captures"][0]["blobs"][0]
    assert got["ingest"]["state"] == "failed"
    url = f"/api/captures/{ref['capture_id']}/reprocess"
    assert client.post(url, json={"photo": got["sha256"]}).json() == {
        "queued": 1, "already": 0,
    }  # fmt: skip
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    assert page["captures"][0]["blobs"][0]["ingest"]["state"] == "queued"
