import hashlib
import json
import os

import pytest

from scrap import importer
from scrap.store import Store

PNG = b"synthetic png bytes"
SHA = hashlib.sha256(PNG).hexdigest()


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)


def front(**fm):
    lines = ["---"]
    for key, value in fm.items():
        if isinstance(value, list):
            lines += [f"{key}:", *(f"  - {v}" for v in value)]
        else:
            lines.append(f"{key}: {value}")
    return "\n".join([*lines, "---", ""])


@pytest.fixture
def vault(tmp_path):
    """A small made-up vault in Thoth's layout."""
    root = tmp_path / "vault"
    write(
        root,
        "notes/alpha.md",
        front(
            title="Alpha",
            type="note",
            created="2025-01-02",
            updated="2025-03-04",
            source="chat",
            tags=["Domain/Testing", "kind/how-to"],
            summary="A made-up note",
            personal="false",
        )
        + "# Alpha\n\nSee [Beta](../entities/beta.md), [root form](entities/beta.md),"
        " [gone](notes/nowhere.md), [an article](../raw/articles/a.md),"
        " [web](https://example.com) and [[beta|wiki beta]].\n\n"
        "![a chart](../raw/assets/chart.png)\n\n![[sketch.excalidraw]]\n\n"
        "![manual](../raw/assets/manual.pdf)\n\n"
        "`[code](beta.md)`\n\n```\n[fenced](beta.md)\n```\n",
    )
    write(
        root,
        "entities/beta.md",
        front(title="Beta", type="entity", created="2025-02-01", updated="2025-02-01")
        + "Back to [Alpha](../notes/alpha.md) and [same folder](gamma.md).\n",
    )
    write(
        root,
        "entities/gamma.md",
        front(title="Gamma", type="entity", created="2025-02-01", updated="2025-02-01"),
    )
    write(
        root,
        "actions/do-it.md",
        front(
            title="Do it",
            type="action",
            created="2025-05-05",
            updated="2025-05-06",
            status="todo",
            due_date="2025-06-01",
            priority="High",
            project="made-up",
        )
        + "Steps.\n",
    )
    write(
        root,
        "media/a-show.md",
        front(
            title="A show",
            type="media",
            created="2025-04-01",
            updated="2025-04-01",
            status="in_progress",
            media_type="tv",
            url="https://example.com/show",
        ),
    )
    write(
        root,
        "memories/day-out.md",
        front(title="Day out", type="memory", memory_date="2001-07-08", tags=["A" * 70])
        + "A day.\n",
    )
    write(root, "notes/alpha-copy.md", front(type="action") + "No title.\n")
    write(root, "notes/more/alpha.md", front(title="Another alpha", type="memory"))
    write(root, "Loose Page.md", "# Loose\n\nNo front matter.\n")
    write(root, "index.md", front(title="Home", type="summary"))
    write(root, "log.md", "log\n")
    write(root, "SCHEMA.md", "schema\n")
    write(root, "images-index.md", front(title="Images", type="summary"))
    write(root, "inbox/held.md", front(type="inbox"))
    write(root, "raw/articles/a.md", "an article\n")
    write(root, "raw/assets/chart.png", PNG)
    write(root, "raw/assets/spare.png", b"unused")
    write(root, "raw/assets/manual.pdf", b"%PDF made up")
    write(root, "raw/assets/sketch.excalidraw.md", "drawing\n")
    write(root, "_bases/view.base", "x\n")
    write(root, "notes/data.json", "{}\n")
    write(root, ".obsidian/app.json", "{}\n")
    return root


def imported(tmp_path, vault, **kw):
    store = Store(tmp_path / "data")
    plan = importer.plan(vault, store)
    importer.run(store, plan, **kw)
    return store, plan


def test_kinds_fields_tags_and_dates(tmp_path, vault):
    store, _ = imported(tmp_path, vault)
    with store.connect() as conn:
        rows = {r["slug"]: dict(r) for r in conn.execute("SELECT * FROM page")}
    assert {s: r["kind"] for s, r in rows.items()} == {
        "alpha": "note",
        "alpha-2": "memory",
        "alpha-copy": "todo",
        "beta": "reference",
        "gamma": "reference",
        "do-it": "todo",
        "a-show": "consume",
        "day-out": "memory",
        "loose-page": "note",
    }
    assert all(r["kind_fixed"] == 1 for r in rows.values())
    # a todo's due date and priority are columns of its own (#104), not fields
    assert json.loads(rows["do-it"]["fields"]) == {"status": "open"}
    assert (rows["do-it"]["due"], rows["do-it"]["priority"]) == ("2025-06-01", "high")
    assert json.loads(rows["a-show"]["fields"]) == {
        "status": "in_progress",
        "subtype": "watch",
        "media_type": "tv",
        "source": "https://example.com/show",
    }
    assert json.loads(rows["alpha"]["fields"]) == {
        "summary": "A made-up note",
        "personal": False,
    }
    assert json.loads(rows["alpha-copy"]["fields"]) == {"status": "open"}
    assert rows["alpha"]["created_at"] == "2025-01-02T12:00:00.000Z"
    assert rows["alpha"]["updated_at"] == "2025-03-04T12:00:00.000Z"
    assert rows["day-out"]["created_at"] == "2001-07-08T12:00:00.000Z"  # memory_date
    assert rows["alpha-copy"]["title"] == "alpha-copy"
    assert rows["loose-page"]["title"] == "Loose"
    page = store.page("alpha")
    assert page["tags"] == ["domain/testing", "kind/how-to"]
    assert page["rev"] == 1 and page["updated_at"] == "2025-03-04T12:00:00.000Z"
    with store.connect() as conn:
        rev = conn.execute("SELECT * FROM page_rev WHERE page_id = ?", (page["id"],))
        assert dict(rev.fetchone())["created_at"] == "2025-03-04T12:00:00.000Z"
    assert store.page("day-out")["tags"] == ["a" * 64]


def test_links_images_and_files(tmp_path, vault):
    store, _ = imported(tmp_path, vault)
    body = store.page("alpha")["body"]
    assert not body.startswith("# Alpha")  # the title is shown already
    assert "See [[beta|Beta]], [[beta|root form]], gone, an article," in body
    assert "[web](https://example.com) and [[beta|wiki beta]]." in body
    assert f"![a chart](/api/blobs/{SHA}/preview?size=2048)" in body
    assert "*sketch.excalidraw (not imported)*" in body
    assert "*manual (attached)*" in body
    assert "`[code](beta.md)`" in body and "[fenced](beta.md)" in body
    beta = store.page("beta")["body"]
    assert beta == "Back to [[alpha|Alpha]] and [[gamma|same folder]]."
    captures = store.page("alpha")["captures"]
    assert [(c["kind"], [b["filename"] for b in c["blobs"]]) for c in captures] == [
        ("photo", ["chart.png"]),
        ("file", ["manual.pdf"]),
    ]
    assert store.blob_path(SHA).read_bytes() == PNG
    assert captures[0]["text"].startswith("---\ntitle: Alpha")  # the original
    assert store.recent(50)[-1]["slug"] == "day-out"  # by its own dates
    assert [p["slug"] for p in store.recent(50) if p["thumb"]] == ["alpha"]
    assert store.search("same folder", 5)[0]["slug"] == "beta"
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM job").fetchone()[0] == 0


def test_report_lists_problems(tmp_path, vault):
    plan = importer.plan(vault, Store(tmp_path / "data"))
    issues = plan.issues
    assert issues["broken link"] == ["notes/alpha.md: notes/nowhere.md"]
    assert issues["link to dropped page"] == ["notes/alpha.md: raw/articles/a.md"]
    assert issues["file not imported"] == [
        "notes/alpha.md: raw/assets/sketch.excalidraw.md"
    ]
    assert issues["unreferenced image"] == ["raw/assets/spare.png"]
    assert issues["no front matter"] == ["Loose Page.md"]
    assert issues["slug collision"] == ["notes/more/alpha.md: alpha-2"]
    assert sorted(issues["tag changed"]) == [
        f"memories/day-out.md: '{'A' * 70}' -> '{'a' * 64}'",
        "notes/alpha.md: 'Domain/Testing' -> 'domain/testing'",
    ]
    assert sorted(issues["unmapped field"]) == [
        "actions/do-it.md: project",
        "notes/alpha.md: source",
    ]
    assert sorted(issues["skipped"]) == [
        "SCHEMA.md: index, log or schema",
        "images-index.md: type summary",
        "index.md: index, log or schema",
        "log.md: index, log or schema",
        "notes/data.json: not a page",
    ]
    assert sorted(issues["dropped folder"]) == [
        "_bases/: 1 files",
        "inbox/: 1 files",
        "raw/: 5 files",
    ]
    text = importer.report(plan, details=False)
    assert text.startswith("9 pages (9 new): 1 consume, 2 memory, 2 note,")
    assert "broken link: 1" in text and "notes/nowhere.md" not in text
    assert "notes/nowhere.md" in importer.report(plan, details=True)


def test_rerun_skips_imported_pages_and_keeps_their_links(tmp_path, vault):
    store, _ = imported(tmp_path, vault)
    write(
        vault,
        "notes/late.md",
        front(title="Late", type="note", created="2025-09-09") + "[B](beta.md)\n",
    )
    write(vault, "entities/beta.md", "changed\n")  # already imported: left as it was
    plan = importer.plan(vault, store)
    assert [p.slug for p in plan.pages if p.new] == ["late"]
    assert importer.run(store, plan) == 1
    assert store.page("late")["body"] == "[[beta|B]]"  # no notes/beta.md: by name
    write(vault, "notes/later.md", front(title="Later") + "[B](../entities/beta.md)\n")
    importer.run(store, importer.plan(vault, store))
    assert store.page("later")["body"] == "[[beta|B]]"
    assert store.page("beta")["body"].startswith("Back to")
    assert len(store.recent(50)) == 11


def test_ingest_queues_the_images(tmp_path, vault):
    store, _ = imported(tmp_path, vault, ingest=True)
    with store.connect() as conn:
        jobs = conn.execute("SELECT source_sha256 FROM job").fetchall()
    assert [j[0] for j in jobs] == [SHA]


def test_cli_dry_run_writes_nothing(tmp_path, vault, capsys):
    from scrap.__main__ import main

    data = tmp_path / "data"
    main(["import", "--dry-run", "--data-dir", str(data), str(vault)])
    out = capsys.readouterr().out
    assert "9 pages (9 new)" in out and "  notes/alpha.md: notes/nowhere.md" in out
    assert not data.exists()
    main(["import", "--data-dir", str(data), str(vault)])
    assert "imported 9 pages" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="no folder"):
        main(["import", "--data-dir", str(data), str(tmp_path / "none")])


def edge_plan(tmp_path, root):
    store = Store(tmp_path / "data")
    plan = importer.plan(root, store)
    importer.run(store, plan)
    return store, plan


def test_dates_and_front_matter(tmp_path):
    root = tmp_path / "v"
    write(root, "notes/quoted.md", '---\ncreated: "2024-03-01"\n---\nq\n')
    write(root, "notes/stamp.md", '---\ncreated: "2024-03-01T10:00:00+02:00"\n---\n')
    write(root, "notes/bad.md", "---\ntype: entity\ncreated: 2024-13-45\n---\nb\n")
    write(root, "notes/junk.md", '---\ncreated: "garbage"\nupdated: 2024-05-05\n---\n')
    write(root, "notes/empty.md", "---\n---\nbody only\n")
    write(root, "notes/compact.md", '---\nupdated: "20240302"\n---\n')
    store, plan = edge_plan(tmp_path, root)
    assert store.page("quoted")["created_at"] == "2024-03-01T12:00:00.000Z"
    assert store.page("stamp")["created_at"] == "2024-03-01T08:00:00.000Z"
    assert store.page("junk")["created_at"] == "2024-05-05T12:00:00.000Z"
    bad = store.page("bad")  # imported as if it had no front matter
    assert bad["kind"] == "note" and bad["body"].startswith("---\ntype: entity")
    assert store.page("empty")["body"] == "body only"
    assert store.page("compact")["created_at"] == "2024-03-02T12:00:00.000Z"
    assert plan.issues["invalid date"] == ["notes/junk.md: created"]
    assert [i.split(":")[0] for i in plan.issues["bad front matter"]] == [
        "notes/bad.md"
    ]
    assert plan.issues["no front matter"] == ["notes/bad.md"]


def test_embeds_anchors_and_ambiguous_names(tmp_path):
    root = tmp_path / "v"
    write(root, "raw/assets/my pic.png", PNG)
    write(root, "raw/assets/logo.svg", b"<svg/>")
    write(
        root,
        "notes/page.md",
        front(title="Page")
        + "![[my pic.png]] ![](../raw/assets/my%20pic.png) ![](../raw/assets/logo.svg)"
        "\n[sec](dup.md#part) [[#A heading]] [[dup]] [[other]] [[odd]]\n"
        "[[memories/dup]] [[../memories/dup.md|up]]\n| [[odd\\|cell]] |\n"
        "```\n```js\n[[dup]]\n```\n[[dup]]\n",
    )
    write(root, "notes/dup.md", front(title="Dup in notes"))
    write(root, "memories/dup.md", front(title="Dup in memories", type="memory"))
    write(root, "inbox/other.md", "held\n")
    write(root, "media/other.md", front(title="Other", type="media"))
    write(root, "entities/odd.md", front(title="'Odd ] [title'", type="entity"))
    store, plan = edge_plan(tmp_path, root)
    body = store.page("page")["body"]
    inline = f"![](/api/blobs/{SHA}/preview?size=2048)"
    assert body.startswith(f"![]({inline[4:]} {inline} *logo.svg (attached)*")
    assert "[[dup-2|sec]] A heading [[dup-2|Dup in notes]] [[other|Other]]" in body
    assert "[[odd|Odd ) (title]]" in body
    assert "[[dup|Dup in memories]] [[dup|up]]\n| [[odd|cell]] |" in body
    assert body.endswith("```\n```js\n[[dup]]\n```\n[[dup-2|Dup in notes]]")
    files = [
        (c["kind"], [b["filename"] for b in c["blobs"]])
        for c in store.page("page")["captures"]
    ]
    assert files == [("photo", ["my pic.png"]), ("file", ["logo.svg"])]
    assert sorted(plan.issues["ambiguous link"]) == [
        "notes/page.md: dup -> notes/dup.md",
        "notes/page.md: dup -> notes/dup.md",  # once more, after the fences
        "notes/page.md: other -> media/other.md",
    ]


def test_symlinks_unreadable_and_large_files_are_skipped(tmp_path, monkeypatch):
    root, outside = tmp_path / "v", tmp_path / "secret.png"
    outside.write_bytes(b"not in the vault")
    write(root, "raw/assets/big.png", b"x" * 2048)
    write(
        root,
        "notes/page.md",
        "![](../raw/assets/link.png) ![](../raw/assets/big.png)\n",
    )
    (root / "raw/assets/link.png").symlink_to(outside)
    (root / "notes/linked.md").symlink_to(outside)
    monkeypatch.setenv("SCRAP_MAX_UPLOAD_MB", "0.001")
    store, plan = edge_plan(tmp_path, root)
    assert sorted(plan.issues["symlink skipped"]) == [
        "notes/linked.md",
        "raw/assets/link.png",
    ]
    assert plan.issues["missing file"] == ["notes/page.md: ../raw/assets/link.png"]
    assert plan.issues["too large"] == ["raw/assets/big.png: over 0 MB"]
    assert "file not imported" not in plan.issues
    assert [p.path for p in plan.pages] == ["notes/page.md"]
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM blob").fetchone()[0] == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads anything")
def test_an_unreadable_page_is_reported(tmp_path):
    root = tmp_path / "v"
    write(root, "notes/ok.md", "fine\n")
    write(root, "notes/locked.md", "secret\n")
    (root / "notes/locked.md").chmod(0)
    try:
        _, plan = edge_plan(tmp_path, root)
    finally:
        (root / "notes/locked.md").chmod(0o644)
    assert [p.path for p in plan.pages] == ["notes/ok.md"]
    assert plan.issues["unreadable"] == ["notes/locked.md: Permission denied"]


def test_odd_tags_and_alias_bombs(tmp_path):
    root = tmp_path / "v"
    write(root, "notes/tags.md", "---\ntags: [null, 7, [x], ok]\n---\n")
    bomb = "\n".join(
        ["a0: &a0 [x, x, x, x, x, x, x, x, x, x]"]
        + [f"a{i}: &a{i} [{', '.join([f'*a{i - 1}'] * 10)}]" for i in range(1, 8)]
    )
    write(root, "notes/bomb.md", f"---\n{bomb}\ntags: [*a7]\n---\n")
    store, plan = edge_plan(tmp_path, root)
    assert store.page("tags")["tags"] == ["7", "ok"]
    assert plan.issues["tag dropped"] == [
        "notes/tags.md: NoneType",
        "notes/tags.md: list",
    ]
    assert plan.issues["bad front matter"] == ["notes/bomb.md: too many aliases"]


def test_search_ignores_link_and_image_addresses(tmp_path, vault):
    store, _ = imported(tmp_path, vault)
    assert store.search("preview", 5) == [] and store.search("2048", 5) == []
    assert store.search("api blobs", 5) == [] and store.search("example", 5) == []
    assert [h["slug"] for h in store.search("chart", 5)] == ["alpha"]  # alt text
    assert [h["slug"] for h in store.search("wiki beta", 5)] == ["alpha"]  # label


def test_a_bad_upload_limit_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_MAX_UPLOAD_MB", "lots")
    with pytest.raises(SystemExit, match="SCRAP_MAX_UPLOAD_MB must be a number"):
        importer.plan(tmp_path, Store(tmp_path / "data"))


def test_long_field_values_are_cut(tmp_path):
    root = tmp_path / "v"
    write(root, "notes/long.md", front(title="Long", summary="word " * 100))
    store, plan = edge_plan(tmp_path, root)
    summary = store.page("long")["fields"]["summary"]
    assert len(summary) == 200 and summary.endswith("word…")
    assert plan.issues["field cut"] == ["notes/long.md: summary: 499 characters"]
    assert "word " * 100 in store.page("long")["captures"][0]["text"]  # all of it


def test_a_file_changed_after_the_plan_stops_the_run(tmp_path):
    root = tmp_path / "v"
    write(root, "raw/assets/a.png", PNG)
    write(root, "raw/assets/b.png", PNG)
    write(root, "notes/a.md", "![](../raw/assets/a.png)\n")
    write(root, "notes/b.md", "![](../raw/assets/b.png)\n")
    store = Store(tmp_path / "data")
    plan = importer.plan(root, store)
    (root / "raw/assets/a.png").write_bytes(PNG.upper())  # same size, new bytes
    with pytest.raises(SystemExit, match="raw/assets/a.png changed since it was"):
        importer.run(store, plan)
    plan = importer.plan(root, store)
    (root / "raw/assets/b.png").unlink()
    with pytest.raises(SystemExit, match="raw/assets/b.png changed since it was"):
        importer.run(store, plan)


def test_links_in_tables_and_indented_code(tmp_path):
    """A link in a table cell keeps the table whole; code (fenced, indented, inline)
    is never rewritten."""
    root = tmp_path / "v"
    write(
        root,
        "notes/page.md",
        front(title="Page")
        + "| Who | Link |\n|---|---|\n| me | [[other]] |\n| you | [b](other.md) |\n\n"
        "    [[other]] in code\n\n`[x](other.md)`\n",
    )
    write(root, "notes/other.md", front(title="Other one"))
    store, _ = edge_plan(tmp_path, root)
    body = store.page("page")["body"]
    assert "| me | [[other\\|Other one]] |\n| you | [[other\\|b]] |" in body
    assert body.endswith("    [[other]] in code\n\n`[x](other.md)`")


def test_a_pipe_in_a_table_links_text_stays_escaped(tmp_path):
    """A link's text, or a page's title, with a pipe in a table cell: every pipe
    escaped, so the cell is not cut in two."""
    root = tmp_path / "v"
    write(
        root,
        "notes/page.md",
        front(title="Page")
        + "| A | B |\n|---|---|\n| [x\\|y](other.md) | [[other]] |\n"
        "| [[other\\|p\\|q]] | z |\n\n[x|y](other.md)\n",
    )
    write(root, "notes/other.md", front(title="One | Two"))
    store, _ = edge_plan(tmp_path, root)
    body = store.page("page")["body"]
    assert "| [[other\\|x\\|y]] | [[other\\|One \\| Two]] |" in body
    assert "| [[other\\|p\\|q]] | z |" in body
    assert body.endswith("[[other|x|y]]")  # outside a table, as it was
