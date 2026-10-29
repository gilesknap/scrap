"""Importing Markdown (#417) from a folder or a zip: an Obsidian vault's pages, links
and files; what is refused (a zip-slip name, too many files); front matter that is
malformed or hostile; the two Claude choices; the API and the CLI."""

import io
import json
import os
import zipfile
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scrap import importer
from scrap.__main__ import main
from scrap.app import create_app
from scrap.store import Store, connect
from test_ingest import jpeg

PDF = b"%PDF-1.4\n%\xe2\xe3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = jpeg(size=(40, 30))  # a JPEG named .png: typed by its name, as Obsidian has it


def write(root: Path, files: Mapping[str, str | bytes]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root


def zipped(files: Mapping[str, str | bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return out.getvalue()


VAULT: dict[str, str | bytes] = {
    "My Note.md": "# My Note\n\nSee [[Other Note|the other]], [[Missing page]] and"
    " [[Other Note#Part]].\n\n![[Pasted image.png]]\n\n![[manual.pdf]]\n\n"
    "| a | b |\n| - | - |\n| [[Other Note\\|o]] | x |\n\n"
    "`[[Other Note]]` and\n\n```\n[[Other Note]]\n```\n",
    "deep/folder/Other Note.md": "---\ntags: work, Home\nstatus: draft\n"
    "cssclasses: [wide]\n---\nBack to [My Note](../../My%20Note.md).\n",
    "deep/Todo list.md": "---\nkind: todo\ntags:\n  - errands\n  - '#Shop'\n"
    "due: 2026-12-01\npriority: high\ncreated: 2026-01-02\n---\n- [ ] milk\n",
    "attachments/Pasted image.png": PNG,
    "attachments/manual.pdf": PDF,
    "attachments/unused.png": PNG + b"x",
    ".obsidian/app.json": "{}",
    ".obsidian/notes.md": "not a page",
    "_templates/t.md": "not a page either",
}


def run(src: Path | bytes, store: Store, **options: Any) -> importer.Done:
    source = importer.source(src if isinstance(src, Path) else io.BytesIO(src))
    try:
        plan = importer.plan(source, store)
        return importer.run(store, source, plan, **options)
    finally:
        source.close()


def rows(store: Store, sql: str, *args: Any) -> list[Any]:
    with closing(connect(store.db)) as conn:
        return [tuple(r) for r in conn.execute(sql, args)]


def page(store: Store, slug: str) -> dict[str, Any]:
    with closing(connect(store.db)) as conn:
        row = conn.execute(
            "SELECT p.*, t.due, t.priority FROM page p LEFT JOIN page_todo t"
            " ON t.page_id = p.id WHERE slug = ?",
            (slug,),
        ).fetchone()
        tags = [r[0] for r in conn.execute("SELECT tag FROM tag WHERE page_id = ?",
                                           (row["id"],))]  # fmt: skip
    return {**dict(row), "fields": json.loads(row["fields"]), "tags": sorted(tags)}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


def test_an_obsidian_vault(tmp_path, store):
    done = run(write(tmp_path / "vault", VAULT), store)
    assert done.new == 3
    tag = importer.import_tag()
    note = page(store, "my-note")
    assert note["title"] == "My Note" and note["kind"] == "note"
    body = note["body"]
    assert body.startswith(
        "# My Note\n\nSee [[other-note|the other]], [[Missing page]]"
    )
    assert "[[other-note|Other Note]]." in body  # #Part: the page (no headings here)
    png = rows(store, "SELECT sha256 FROM capture_blob WHERE filename = ?",
               "Pasted image.png")[0][0]  # fmt: skip
    assert f"![](/api/blobs/{png}/preview?size=2048)" in body
    pdf = rows(store, "SELECT sha256 FROM capture_blob WHERE filename = ?",
               "manual.pdf")[0][0]  # fmt: skip
    assert f"[manual.pdf](/api/blobs/{pdf})" in body
    assert "| [[other-note\\|o]] | x |" in body  # a pipe in a table stays escaped
    assert "`[[Other Note]]`" in body and "```\n[[Other Note]]\n```" in body  # code
    other = page(store, "other-note")
    assert other["tags"] == sorted(["work", "home", tag])  # a string of tags
    assert other["fields"] == {"status": "draft"}  # a list is no field
    assert other["body"] == "Back to [[my-note|My Note]]."
    todo = page(store, "todo-list")
    assert (todo["kind"], todo["due"], todo["priority"]) == (
        "todo",
        "2026-12-01",
        "high",
    )
    assert todo["tags"] == sorted(["errands", "shop", tag])
    assert todo["created_at"] == "2026-01-02T12:00:00.000Z"
    assert todo["task_total"] == 1
    assert {r[0] for r in rows(store, "SELECT source FROM capture")} == {"import"}
    assert rows(store, "SELECT count(*) FROM page WHERE slug LIKE '%notes%'")[0] == (0,)


def test_the_plan_reports_what_it_could_not_do(tmp_path, store):
    source = importer.source(write(tmp_path / "vault", VAULT))
    plan = importer.plan(source, store)
    source.close()
    issues = {k: [i.split(":")[0] for i in v] for k, v in plan.issues.items()}
    assert issues["broken link"] == ["My Note.md"]
    assert issues["folder skipped"] == [".obsidian/", "_templates/"]
    assert issues["file not used by a new page"] == ["attachments/unused.png"]
    assert "field not imported" in issues  # cssclasses
    assert not store.db.exists()  # a plan writes nothing


def test_a_slug_in_use_is_suffixed_and_links_follow_it(tmp_path, store):
    run(write(tmp_path / "one", {"other-note.md": "Mine\n"}), store)
    run(write(tmp_path / "vault", VAULT), store)
    assert page(store, "other-note")["body"] == "Mine"  # never overwritten
    assert page(store, "other-note-2")["title"] == "Other Note"
    assert "[[other-note-2|the other]]" in page(store, "my-note")["body"]


def test_a_store_s_pinned_page_is_kept(tmp_path, store):
    store.migrate()
    store.ensure_pinned("me")
    done = run(write(tmp_path / "a", {"pinned.md": "Pinned\n- [[x]]\n"}), store)
    assert (done.new, done.skipped) == (0, 1)
    assert page(store, "pinned")["body"] == "# Pinned\n\n"
    assert rows(store, "SELECT count(*) FROM page") == [(1,)]


# ---- refused, and hostile front matter


@pytest.mark.parametrize(
    "name", ["../evil.md", "a/../../evil.md", "/etc/evil.md", "C:evil.md", "a\\b.md"]
)
def test_a_zip_slip_name_refuses_the_archive(tmp_path, store, name):
    data = zipped({"fine.md": "fine\n", name: "evil\n"})
    with pytest.raises(importer.RefusedError, match="a file named"):
        importer.source(io.BytesIO(data))
    assert not (tmp_path / "evil.md").exists()
    assert not store.db.exists()


def test_too_many_files_or_bytes_refuse_the_archive(monkeypatch):
    data = zipped({f"p{i}.md": "x" * 100 for i in range(5)})
    monkeypatch.setattr("scrap.importer.sources.MAX_ENTRIES", 4)
    with pytest.raises(importer.RefusedError, match="more than 4 files"):
        importer.source(io.BytesIO(data))
    monkeypatch.setattr("scrap.importer.sources.MAX_ENTRIES", 10)
    with pytest.raises(importer.RefusedError, match="unpacked"):
        importer.source(io.BytesIO(data), total=400)
    assert importer.source(io.BytesIO(data), total=500).files


def test_not_a_zip_is_refused():
    with pytest.raises(importer.RefusedError, match="not a zip"):
        importer.source(io.BytesIO(b"PK\x03\x04 but not really"))


def test_a_folder_s_symlinks_are_not_followed(tmp_path, store):
    outside = write(tmp_path / "outside", {"secret.md": "secret\n", "s.png": PNG})
    vault = write(tmp_path / "vault", {"a.md": "A ![x](s.png) [[secret]]\n"})
    (vault / "s.png").symlink_to(outside / "s.png")
    (vault / "secret.md").symlink_to(outside / "secret.md")
    (vault / "linked").symlink_to(outside, target_is_directory=True)
    assert run(vault, store).new == 1
    assert page(store, "a")["body"] == "A ![x](s.png) [[secret]]"  # kept as typed
    assert rows(store, "SELECT count(*) FROM blob") == [(0,)]


@pytest.mark.parametrize(
    "head",
    [
        "title: [unclosed",  # not YAML
        "!!python/object/apply:os.system ['touch pwned']",  # never run: safe_load
        "a: &x [1]\n" + "\n".join(f"b{i}: *x" for i in range(70)),  # an alias bomb
        "- a list\n- not a map",
        "created: 2026-02-30",  # not a date
    ],
)
def test_malformed_front_matter_keeps_the_whole_text(tmp_path, store, head):
    text = f"---\n{head}\n---\nThe text\n"
    run(write(tmp_path / "v", {"odd.md": text}), store)
    got = page(store, "odd")
    assert got["body"] == text.removesuffix("\n")  # nothing lost
    assert got["kind"] == "note"
    assert not (tmp_path / "pwned").exists() and not Path("pwned").exists()


def test_odd_values_are_left_out_not_failed(tmp_path, store):
    text = (
        "---\nkind: robot\nid: not-a-ulid\nbig: .inf\nhuge: 99999999999999999999\n"
        f"long: {'x' * 300}\n{'k' * 41}: 1\ntags: [ok, {'t' * 70}, 3]\n"
        "made_by: someone\n---\nBody\n"
    )
    run(write(tmp_path / "v", {"odd.md": text}), store)
    got = page(store, "odd")
    assert got["kind"] == "note" and got["made_by"] == "human"
    assert got["fields"] == {"long": "x" * 199 + "…"}
    assert got["tags"] == sorted(["ok", "3", importer.import_tag()])


def test_dates_out_of_range_and_the_import_tag_given_already(tmp_path, store):
    tag = importer.import_tag()
    text = f"---\ncreated: 0001-01-01T00:00:00+05:00\ntags: [{tag}]\n---\nOld\n"
    run(write(tmp_path / "v", {"old.md": text}), store)
    assert page(store, "old")["tags"] == [tag]  # once


def test_a_zip_entry_with_an_impossible_time_is_read(store):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(zipfile.ZipInfo("a.md", (2026, 13, 40, 0, 0, 0)), "A\n")
    assert run(out.getvalue(), store).new == 1
    assert page(store, "a")["created_at"] == "1980-01-01T00:00:00.000Z"


def test_a_page_whose_links_grow_past_the_limit_is_skipped(
    tmp_path, store, monkeypatch
):
    monkeypatch.setattr("scrap.importer.pipeline.MAX_PAGE", 60)
    files = {"a.md": "![](x.png) ![](x.png)\n", "x.png": PNG}
    assert run(write(tmp_path / "v", files), store).new == 0


def test_topic_and_gc_pages_are_not_imported(tmp_path, store):
    files = {
        "t.md": '---\nmade_by: "topic"\n---\n',
        "g.md": '---\nmade_by: "gc"\n---\nreview\n',
        "c.md": '---\nmade_by: "claude"\n---\nby Claude\n',
    }
    assert run(write(tmp_path / "v", files), store).new == 1
    assert page(store, "c")["made_by"] == "claude"


def test_a_page_too_large_is_skipped(tmp_path, store, monkeypatch):
    monkeypatch.setattr("scrap.importer.pipeline.MAX_PAGE", 10)
    files = {"big.md": "x" * 11, "small.md": "[[big]]\n"}
    assert run(write(tmp_path / "v", files), store).new == 1
    assert page(store, "small")["body"] == "[[big]]"


def test_an_id_used_twice_makes_two_pages(tmp_path, store):
    head = '---\nid: "01JBC6Z9Q3W1N8X5T2R7M4K0AD"\n---\n'
    files = {"a.md": head + "A\n", "b.md": head + "B\n"}
    assert run(write(tmp_path / "v", files), store).new == 2
    assert page(store, "a")["id"] == "01JBC6Z9Q3W1N8X5T2R7M4K0AD"
    assert page(store, "b")["id"] != "01JBC6Z9Q3W1N8X5T2R7M4K0AD"


# ---- the two Claude choices


def jobs(store: Store) -> tuple[list[Any], list[Any]]:
    enrich = rows(store, "SELECT p.slug, e.reason FROM enrich_job e"
                  " JOIN page p ON p.id = e.page_id ORDER BY p.slug")  # fmt: skip
    ingest = rows(store, "SELECT p.slug, b.mime FROM job j JOIN capture c"
                  " ON c.id = j.capture_id JOIN page p ON p.id = c.page_id JOIN blob b"
                  " ON b.sha256 = j.source_sha256 ORDER BY p.slug, b.mime")  # fmt: skip
    return enrich, ingest


@pytest.fixture
def claude_on(monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.delenv("SCRAP_ENRICH", raising=False)


@pytest.mark.parametrize(
    "enrich, photos, want_enrich, want_ingest",
    [
        (False, False, [], [("my-note", "application/pdf")]),  # files: read locally
        (True, False, [("other-note", "backfill"), ("todo-list", "backfill")],
         [("my-note", "application/pdf")]),
        (False, True, [],
         [("my-note", "application/pdf"), ("my-note", "image/png")]),
    ],
)  # fmt: skip
def test_each_choice_queues_its_own_jobs_only(
    tmp_path, store, claude_on, enrich, photos, want_enrich, want_ingest
):
    done = run(write(tmp_path / "v", VAULT), store, enrich=enrich, photos=photos)
    assert jobs(store) == (want_enrich, sorted(want_ingest))
    assert (done.enrich, done.photos, done.files) == (
        len(want_enrich), int(photos), 1,
    )  # fmt: skip


def test_enrich_off_queues_no_enrich(tmp_path, store, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "on")
    monkeypatch.setenv("SCRAP_ENRICH", "off")
    done = run(write(tmp_path / "v", VAULT), store, enrich=True)
    assert done.enrich == 0 and jobs(store)[0] == []


def test_the_cost_of_each_is_rough_but_priced(monkeypatch):
    assert 0.002 < importer.per_page() < 0.01  # Haiku: tags, summary, related
    assert 0.02 < importer.per_photo() < 0.2  # Opus reading a photo
    monkeypatch.setenv("SCRAP_VISION_MODEL", "claude-haiku-5-5")
    assert importer.per_photo() < 0.01


# ---- the API and the CLI


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "data"))


def test_the_api_imports_a_zip(client, store, claude_on):
    terms = client.get("/api/import").json()
    assert terms["max_upload_bytes"] == 50 << 20
    assert terms["enrich"] is True and terms["photos"] is True
    assert terms["page_usd"] == round(importer.per_page(), 4)
    files = {"file": ("vault.zip", zipped(VAULT), "application/zip")}
    r = client.post("/api/import", files=files, data={"enrich": "1"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["new"], got["skipped"], got["enrich"], got["photos"]) == (3, 0, 2, 0)
    assert got["tag"] == importer.import_tag()
    assert got["issues"]["broken link"]["count"] == 1
    assert rows(store, "SELECT DISTINCT author FROM capture") == [("tagged",)]
    again = client.post("/api/import", files=files).json()
    assert (again["new"], again["skipped"]) == (0, 3)


def test_the_api_refuses_what_it_cannot_import(client, store, monkeypatch):
    bad = zipped({"../x.md": "x"})
    r = client.post("/api/import", files={"file": ("a.zip", bad, "application/zip")})
    assert r.status_code == 422 and "a file named" in r.json()["detail"]
    r = client.post("/api/import", files={"file": ("a.zip", b"no", "application/zip")})
    assert r.status_code == 422 and "not a zip" in r.json()["detail"]
    assert client.post("/api/import", data={"enrich": "1"}).status_code == 422
    assert rows(store, "SELECT count(*) FROM page") == [(0,)]


def test_the_api_refuses_a_zip_over_the_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_MAX_UPLOAD_MB", "0.01")
    client = TestClient(create_app(tmp_path / "data"))
    big = zipped({"a.md": "x", "b.png": os.urandom(20_000)})
    r = client.post("/api/import", files={"file": ("a.zip", big, "application/zip")})
    assert r.status_code == 413


def test_the_cli_dry_run_writes_nothing(tmp_path, store, capsys):
    vault = write(tmp_path / "vault", VAULT)
    main(["import", "--data-dir", str(store.dir), "--dry-run", str(vault)])
    out = capsys.readouterr().out
    assert "3 pages, 3 new" in out and "broken link: 1" in out
    assert "  My Note.md: Missing page" in out  # each problem, with --dry-run
    assert "Claude, roughly: $" in out and "2 text pages" in out
    assert not store.dir.exists()  # not even an empty database


def test_the_cli_imports_a_zip(tmp_path, store, capsys):
    path = tmp_path / "vault.zip"
    path.write_bytes(zipped(VAULT))
    main(["import", "--data-dir", str(store.dir), str(path)])
    assert "imported 3 pages" in capsys.readouterr().out
    main(["import", "--data-dir", str(store.dir), str(path)])
    out = capsys.readouterr().out
    assert "imported 0 pages" in out and "3 here already" in out
    with pytest.raises(SystemExit, match="no folder or zip"):
        main(["import", "--data-dir", str(store.dir), str(tmp_path / "nothing")])
