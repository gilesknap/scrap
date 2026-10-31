"""The whole store's Markdown export (#417): `<slug>.md` per page with the owner's data
only, model text in `_claude/`, the originals in `files/`; a folder from `scrap export`,
or a zip streamed from GET /api/store/download. It opens as an Obsidian vault."""

import hashlib
import io
import re
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from scrap import export as export_module
from scrap.export import SIDECAR, export
from scrap.markdown import wiki_targets
from scrap.store import Store, connect, new_ulid, now, writeups
from test_drawing import scene
from test_ingest import jpeg
from test_mcp import ok

PDF = b"%PDF-1.4\n%\xe2\xe3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
# What a model wrote on the image page; none of it may be in a page's own file
MODEL_TEXT = (
    "A whiteboard with three boxes",
    "SPRINT PLAN OCR",
    "Claude's summary of the board",
    "Write-up of the sprint board",
    "claude-tag",
)


@pytest.fixture
def data(tmp_path):
    return tmp_path / "data"


def sql(data: Path, query: str, *args: Any) -> None:
    with closing(connect(data / "scrap.db")) as conn:
        conn.execute(query, args)
        conn.commit()


def add(client, text: str, **extra: Any) -> dict[str, Any]:
    r = client.post("/api/captures", json={"id": new_ulid(), "text": text, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def split(text: str) -> tuple[dict[str, Any], str]:
    """A file's front matter, parsed as YAML, and its body."""
    assert text.startswith("---\n")
    head, _, body = text[4:].partition("\n---\n")
    return yaml.safe_load(head), body


def vault_problems(root: Path) -> list[str]:
    """What would not open cleanly as an Obsidian vault: front matter that is not YAML,
    a [[link]] (or an attachment's) naming no file, a relative link to no file."""
    problems = []
    for md in root.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        try:
            front, body = split(text)
        except (AssertionError, yaml.YAMLError) as error:
            problems.append(f"{md}: front matter: {error}")
            continue
        links = [*wiki_targets(body), *front.get("attachments", [])]
        for link in links:
            target = link.strip("[]").split("#")[0]
            if not (root / target).is_file() and not (root / f"{target}.md").is_file():
                problems.append(f"{md.relative_to(root)}: [[{target}]]")
        for href in re.findall(
            r"\]\(((?:\.\./)?files/[^)\s]+|\.\./[^)\s]+\.md)\)", body
        ):
            if not (md.parent / href).resolve().is_file():
                problems.append(f"{md.relative_to(root)}: ({href})")
    return problems


@pytest.fixture
def store_pages(client, data):
    """A note with links and tags, a todo, an image page with a PDF and everything a
    model makes of a photo, and a page in the trash."""
    other = add(client, "RTEMS iocs\nabout them")
    slug = other["slug"]
    text = f"Notes on ibek\nSee [[{slug}]] and [[{slug}|the RTEMS page]]."
    note = add(client, text, tags=["epics/ibek", "work"])
    todo = add(
        client,
        "Renew passport\n- [ ] forms\n- [x] photo",
        kind="todo",
        due="2026-11-15",
        priority="high",
    )
    files = [
        ("file", ("board.jpg", jpeg(size=(800, 600)), "image/jpeg")),
        ("file", ("plan.pdf", PDF, "application/pdf")),
    ]
    board = client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "Sprint board\nmy typed notes"},
        files=files,
    ).json()
    page = client.get(f"/api/pages/{board['page_id']}").json()
    cap = page["captures"][0]
    photo, pdf = (b["sha256"] for b in cap["blobs"])
    stamp = now()
    board_kind = '{"kind": "whiteboard"}'  # a board: its write-up is shown
    for kind, text in (("description", MODEL_TEXT[0]), ("ocr", MODEL_TEXT[1])):
        sql(data, "INSERT INTO derived (capture_id, source_sha256, kind, version,"
            " producer, text, data, created_at) VALUES (?, ?, ?, 1, 'm', ?, ?, ?)",
            cap["id"], photo, kind, text, board_kind, stamp)  # fmt: skip
    url = f"/api/captures/{cap['id']}/photos/{photo}/drawing"
    put = client.put(url, json={"base_version": None, "scene": scene("BOX")})
    assert put.status_code == 200, put.text
    sql(data, "UPDATE page SET kind = 'whiteboard' WHERE id = ?", board["page_id"])
    sql(data, "INSERT INTO tag VALUES (?, 'claude-tag')", board["page_id"])
    sql(data, "INSERT INTO model_tag VALUES (?, 'claude-tag', 'on', 'm', ?)",
        board["page_id"], stamp)  # fmt: skip
    with closing(connect(data / "scrap.db")) as conn:
        writeups.put(
            conn, board["page_id"], stamp, producer="m", run_id=None,
            prompt_version="1", summary=MODEL_TEXT[2], text=MODEL_TEXT[3],
            guidance=None,
        )  # fmt: skip
        conn.commit()
    binned = add(client, "Binned page")
    client.delete(f"/api/pages/{binned['page_id']}")
    return {
        "other": other, "note": note, "todo": todo, "board": board,
        "photo": photo, "pdf": pdf,
    }  # fmt: skip


def test_a_note_has_its_title_tags_and_dates_as_yaml(
    client, data, store_pages, tmp_path
):
    out = tmp_path / "md"
    assert export(Store(data), out) == 4  # not the trashed one
    ref = store_pages["note"]
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    front, body = split((out / f"{ref['slug']}.md").read_text(encoding="utf-8"))
    assert front == {
        "title": "Notes on ibek",
        "aliases": ["Notes on ibek"],
        "id": ref["page_id"],
        "kind": "note",
        "tags": ["epics/ibek", "work"],
        "created": datetime.fromisoformat(page["created_at"]),
        "updated": datetime.fromisoformat(page["updated_at"]),
    }
    assert body == f"\n{page['body']}\n"  # byte for byte
    assert not (out / SIDECAR / f"{ref['slug']}.md").exists()  # nothing by a model
    assert not (out / "binned-page.md").exists()


def test_links_are_kept_as_typed_and_name_a_file(data, store_pages, tmp_path):
    out = tmp_path / "md"
    export(Store(data), out)
    slug = store_pages["other"]["slug"]
    text = (out / f"{store_pages['note']['slug']}.md").read_text(encoding="utf-8")
    assert f"See [[{slug}]] and [[{slug}|the RTEMS page]]." in text
    assert (out / f"{slug}.md").is_file()
    assert vault_problems(out) == []


def test_a_todo_has_due_priority_and_status_and_keeps_its_boxes(
    data, store_pages, tmp_path
):
    out = tmp_path / "md"
    export(Store(data), out)
    front, body = split(
        (out / f"{store_pages['todo']['slug']}.md").read_text(encoding="utf-8")
    )
    assert front["kind"] == "todo"
    assert (front["due"], front["priority"], front["status"]) == (
        "2026-11-15", "high", "open",
    )  # fmt: skip
    assert "tasks" not in front and "fields" not in front  # recounted; flattened
    assert "- [ ] forms\n- [x] photo" in body


def test_an_image_page_embeds_its_photo_and_lists_its_pdf(data, store_pages, tmp_path):
    out = tmp_path / "md"
    export(Store(data), out)
    slug = store_pages["board"]["slug"]
    front, body = split((out / f"{slug}.md").read_text(encoding="utf-8"))
    photo, pdf = f"{store_pages['photo']}.jpg", f"{store_pages['pdf']}.pdf"
    assert front["kind"] == "whiteboard"
    assert front["attachments"] == [f"[[files/{pdf}]]"]
    assert "tags" not in front  # its only tag is Claude's
    assert f"![](files/{photo})" in body and "my typed notes" in body
    assert (out / "files" / photo).read_bytes()[:2] == b"\xff\xd8"
    assert (out / "files" / pdf).read_bytes() == PDF
    assert vault_problems(out) == []


def test_model_text_is_only_in_the_sidecar(data, store_pages, tmp_path):
    out = tmp_path / "md"
    export(Store(data), out)
    for md in out.glob("*.md"):  # the pages: none of it, nor a drawing
        text = md.read_text(encoding="utf-8")
        assert not [t for t in MODEL_TEXT if t in text], md
        assert ".excalidraw" not in text and "Claude" not in text
    slug = store_pages["board"]["slug"]
    sidecar = (out / SIDECAR / f"{slug}.md").read_text(encoding="utf-8")
    front, notes = split(sidecar)
    assert front == {"generated_by": "claude", "page": slug}
    assert "Written by a model" in notes and f"(../{slug}.md)" in notes
    for text in MODEL_TEXT:
        assert text in notes
    assert f"> {MODEL_TEXT[0]}" in notes and f"```text\n{MODEL_TEXT[1]}\n```" in notes
    [drawing] = re.findall(r"\(\.\./files/([^)]+\.excalidraw)\)", notes)
    assert "BOX" in (out / "files" / drawing).read_text(encoding="utf-8")
    assert [p.name for p in (out / SIDECAR).iterdir()] == [f"{slug}.md"]


def test_sidecar_links_are_relative_paths(client, data, tmp_path):
    """[[slug]] in model text, written as ../<slug>.md: in _claude/ a [[slug]] would
    find the sidecar of that name before the page."""
    a, b = add(client, "Alpha"), add(client, "Beta")
    stamp = now()
    like = f"Like [[{b['slug']}]]."
    sql(data, "INSERT INTO enrichment (page_id, producer, summary, updated_at)"
        " VALUES (?, 'm', ?, ?)", a["page_id"], like, stamp)  # fmt: skip
    sql(data, "INSERT INTO enrichment (page_id, producer, summary, updated_at)"
        " VALUES (?, 'm', 'B', ?)", b["page_id"], stamp)  # fmt: skip
    out = tmp_path / "md"
    export(Store(data), out)
    notes = (out / SIDECAR / f"{a['slug']}.md").read_text(encoding="utf-8")
    assert f"> Like [{b['slug']}](../{b['slug']}.md)." in notes and "[[" not in notes
    assert vault_problems(out) == []


@pytest.mark.parametrize(
    "tags",
    [
        ["has space", "colon: here", 'quote "x"', "back\\slash"],
        ["#not-a-heading", "- dash", "[bracket]", "{brace}", "yes", "null", "1.5"],
        ["ünïcödé", "日本語", "emoji 🎉", "a/b/c", "x'y", "*star", "&amp", "!bang"],
    ],
)
def test_tags_and_titles_that_need_escaping_parse_back(client, data, tmp_path, tags):
    title = 'Tricky: "quoted" #1 \u2028 \x85 — 🎉 [x] {y}'
    ref = add(client, f"{title}\nbody", tags=tags)
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    sql(data, "UPDATE page SET fields = ? WHERE id = ?",
        '{"status": "a: b", "title": "a field", "n": 3, "ok": true,'
        ' "x: y #z": 1, "- [q]\\nr": "s", "on": "x", "Null": 2}',
        ref["page_id"])  # fmt: skip
    out = tmp_path / "md"
    export(Store(data), out)
    front, _ = split((out / f"{ref['slug']}.md").read_text(encoding="utf-8"))
    assert front["title"] == page["title"] and front["aliases"] == [page["title"]]
    assert front["tags"] == page["tags"]  # as stored, spaces and all
    assert (front["status"], front["n"], front["ok"]) == ("a: b", 3, True)
    assert front["fields"] == {"title": "a field"}  # a field named as one of scrap's
    names = ("x: y #z", "- [q]\nr", "on", "Null")  # free text: quoted
    assert [front[n] for n in names] == [1, "s", "x", 2]


def test_made_by_is_there_only_when_not_the_owner(data, tmp_path):
    store = Store(data)
    store.migrate()
    page = ok(store, "write", title="By Claude", body="text", origin="o")
    out = tmp_path / "md"
    export(store, out)
    front, _ = split((out / f"{page['slug']}.md").read_text(encoding="utf-8"))
    assert front["made_by"] == "claude"


def tree(data: Path) -> tuple[list[str], dict[str, str]]:
    """The database's every row, and each stored file's hash."""
    with closing(connect(data / "scrap.db")) as conn:
        rows = list(conn.iterdump())
    files = {
        str(p.relative_to(data)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((data / "files").rglob("*"))
        if p.is_file()
    }
    return rows, files


def test_exporting_never_changes_the_store(client, data, store_pages, tmp_path):
    before = tree(data)
    export(Store(data), tmp_path / "md")
    assert client.get("/api/store/download").status_code == 200
    assert tree(data) == before


def test_the_download_is_the_export_as_a_zip(client, data, store_pages, tmp_path):
    r = client.get("/api/store/download", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "content-encoding" not in r.headers  # not gzipped again
    assert r.headers["cache-control"] == "no-store"
    assert re.fullmatch(
        r'attachment; filename="scrap-export-\d{4}-\d\d-\d\d\.zip"; .*',
        r.headers["content-disposition"],
    )
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert zf.testzip() is None
    out = tmp_path / "md"
    export(Store(data), out)
    folder = {
        str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*") if p.is_file()
    }
    assert {n: zf.read(n) for n in zf.namelist()} == folder
    photo = zf.getinfo(f"files/{store_pages['photo']}.jpg")
    assert photo.compress_type == zipfile.ZIP_STORED  # compressed already


def test_the_zip_is_sent_a_chunk_at_a_time(client, data, monkeypatch):
    """A big file goes out in CHUNK pieces as it is read, never whole in memory."""
    monkeypatch.setattr(export_module, "CHUNK", 1 << 12)
    big = bytes(range(256)) * 400  # 100 kB
    client.post(
        "/api/captures",
        data={"id": new_ulid(), "text": "Big"},
        files=[("file", ("big.bin", big, "application/octet-stream"))],
    )
    chunks = list(export_module.stream(Store(data)))
    assert max(len(c) for c in chunks) < 3 * (1 << 12)
    zf = zipfile.ZipFile(io.BytesIO(b"".join(chunks)))
    [name] = [n for n in zf.namelist() if n.startswith("files/")]
    assert zf.read(name) == big


def test_a_file_gone_since_is_left_out(client, data, store_pages, monkeypatch):
    entries = export_module._entries

    def gone(store):  # scrap gc deletes it after the pages were read
        out = entries(store)
        Store(data).blob_path(store_pages["pdf"]).unlink()
        return out

    monkeypatch.setattr(export_module, "_entries", gone)
    zf = zipfile.ZipFile(io.BytesIO(client.get("/api/store/download").content))
    assert zf.testzip() is None
    assert f"files/{store_pages['pdf']}.pdf" not in zf.namelist()


def test_a_file_gone_since_is_left_out_of_the_folder(data, store_pages, tmp_path):
    from scrap.export import _entries

    def gone(store):  # scrap gc deletes it after the pages were read
        entries, count = _entries(store)
        Store(data).blob_path(store_pages["pdf"]).unlink()
        return entries, count

    out = tmp_path / "md"
    with pytest.MonkeyPatch.context() as m:
        m.setattr(export_module, "_entries", gone)
        assert export(Store(data), out) == 4
    assert not (out / "files" / f"{store_pages['pdf']}.pdf").exists()
    assert (out / "files" / f"{store_pages['photo']}.jpg").is_file()


def test_an_empty_store_exports_an_empty_vault(client, tmp_path, data):
    assert export(Store(data), tmp_path / "md") == 0
    zf = zipfile.ZipFile(io.BytesIO(client.get("/api/store/download").content))
    assert zf.namelist() == []


def test_sidecar_links_skip_what_the_pwa_shows_as_text():
    """Model text's [[Some Title]] is kept, not made a link to no file; a table
    cell's label keeps its pipe escaped (#491)."""
    text = "[[Some Title]] [[a#h|A]]\n\n| [[a\\|x\\|y]] |\n| - |"
    assert export_module._sidecar_links(text) == (
        "[[Some Title]] [A](../a.md)\n\n| [x\\|y](../a.md) |\n| - |"
    )
