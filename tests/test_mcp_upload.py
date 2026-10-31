"""MCP clients add files to pages (#480): add_svg, and the /mcp upload behind the
bearer token; both Claude's revisions, and both off with SCRAP_MCP_UPLOAD."""

from contextlib import closing

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client

from scrap import mcp_server, svg
from scrap.app import create_app
from scrap.store import Store, connect, new_ulid
from test_mcp import LOCAL, SECRET, bearer, human, ok, refused
from test_svg import EVIL, NS, TRIANGLE

PAPER = "Q1 Find the hypotenuse.\nShow your working.\n\nQ2 Factorise 12."
DOT = f'<svg {NS} viewBox="0 0 10 10"><title>Dot</title><circle r="4"/></svg>'


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def tools(store) -> set[str]:
    async def main():
        async with Client(mcp_server.server(store)) as client:
            return {t.name for t in (await client.list_tools()).tools}

    return anyio.run(main)


def found(store, query):
    return {r["slug"] for r in ok(store, "search", query=query)["results"]}


def test_add_svg_embeds_it_after_the_question_as_claudes_revision(store):
    ref = human(store, PAPER)
    out = ok(store, "add_svg", page=ref["slug"], svg=TRIANGLE.decode(),
             alt="A right [angled] triangle", after="hypotenuse.",
             filename="q1")  # fmt: skip
    sha = out["sha256"]
    embed = f"![A right (angled) triangle](/api/blobs/{sha}/preview?size=2048)"
    assert out["embed"] == embed and out["changed"] and out["created"]
    assert (out["rev_before"], out["rev"], out["filename"]) == (1, 2, "q1.svg")
    assert out["download_url"].endswith(f"/mcp/blobs/{sha}?download=1")
    assert f"+{embed}" in out["diff"]
    p = store.page(ref["slug"])
    assert p["body"] == (
        f"Q1 Find the hypotenuse.\n\n{embed}\n\nShow your working.\n\nQ2 Factorise 12."
    )
    blob = p["captures"][1]["blobs"][0]
    assert (blob["sha256"], blob["mime"], blob["filename"]) == (
        sha, "image/svg+xml", "q1.svg",
    )  # fmt: skip
    assert p["captures"][1]["author"] == "claude"
    assert p["captures"][1]["source"] == "mcp"
    assert store.blob(sha)[0].read_bytes() == svg.sanitise(TRIANGLE)
    text = ok(store, "revisions", page=ref["slug"])["text"]
    assert [(r["rev"], r["author"]) for r in text] == [
        (2, "claude"), (1, "giles@example.com"),
    ]  # fmt: skip
    assert found(store, "is:claude-edited") == {ref["slug"]}
    # revert removes the embed, as for a photo added in the PWA; the file is kept
    ok(store, "revert", page=ref["slug"], to_rev=1, rev=2)
    p = store.page(ref["slug"])
    assert p["body"] == PAPER and p["rev"] == 3
    assert sha in p["removed"]


def test_add_svg_goes_at_the_end_by_default_and_a_dry_run_saves_nothing(store):
    ref = human(store, PAPER)
    key = ref["page_id"]
    dry = ok(store, "add_svg", page=key, svg=DOT, alt="A dot", dry_run=True)
    assert dry["dry_run"] and dry["changed"] and not dry["created"]
    assert (dry["rev_before"], dry["rev"]) == (1, 2)
    p = store.page(ref["slug"])
    assert p["rev"] == 1 and len(p["captures"]) == 1
    out = ok(store, "add_svg", page=key, svg=DOT, alt="A dot", key="k1")
    assert out["diff"] == dry["diff"] and out["sha256"] == dry["sha256"]
    assert store.page(ref["slug"])["body"] == f"{PAPER}\n\n{out['embed']}"
    assert out["filename"] == "diagram.svg"
    again = ok(store, "add_svg", page=key, svg=DOT, alt="A dot", key="k1")
    assert not again["created"] and not again["changed"] and again["rev"] == 2
    assert len(store.page(ref["slug"])["captures"]) == 2  # the retry added nothing
    files = sorted(p.name for p in (store.dir / "files").rglob("*") if p.is_file())
    other = DOT.replace('r="4"', 'r="3"')
    for dry in (True, False):  # a dry run says so too: it shows no diff
        error = refused(store, "add_svg", page=key, svg=other, alt="A dot", key="k1",
                        dry_run=dry)  # fmt: skip
        assert "key was used for another SVG" in error
    retry = ok(store, "add_svg", page=key, svg=DOT, alt="A dot", key="k1", dry_run=True)
    assert not retry["changed"] and retry["rev"] == 2  # as the retry itself
    after = sorted(p.name for p in (store.dir / "files").rglob("*") if p.is_file())
    assert after == files  # nothing stored for the refused one


def test_add_svg_refusals(store):
    ref = human(store, "a cat, a cat and a dog")
    slug = ref["slug"]
    for args, why in [
        ({"after": "horse"}, "is not in the page's body"),
        ({"after": "a cat"}, "occurs more than once"),
        ({"svg": "<html/>"}, "root element must be <svg>"),
        ({"svg": '<!DOCTYPE svg [<!ENTITY a "x">]><svg/>'}, "DOCTYPE"),
        ({"svg": f"<svg {NS}>" + " " * svg.MAX_SVG + "</svg>"}, "over 1024 KiB"),
        ({"alt": "   "}, "alt must not be empty"),
        ({"page": "no-such-page"}, "no such page"),
    ]:
        error = refused(store, "add_svg", **{"page": slug, "svg": DOT, "alt": "x",
                                             **args})  # fmt: skip
        assert why in error, (args, error)
    assert store.page(slug)["rev"] == 1


def test_malicious_markup_is_stored_neutralised(store):
    ref = human(store, "Diagram")
    out = ok(store, "add_svg", page=ref["slug"], svg=EVIL.decode(), alt="evil")
    stored = store.blob(out["sha256"])[0].read_bytes()
    assert b"script" not in stored and b"evil.example" not in stored
    assert b"onload" not in stored and b"foreignObject" not in stored


def test_content_edit_off_does_not_limit_add_svg(store, monkeypatch):
    monkeypatch.setenv("SCRAP_MCP_CONTENT_EDIT", "0")  # only SCRAP_MCP_UPLOAD does
    mine = human(store, PAPER)
    assert ok(store, "add_svg", page=mine["slug"], svg=DOT, alt="d")["changed"]


def test_add_svg_wakes_the_worker(store):
    woken = []

    async def main(**args):
        async with Client(mcp_server.server(store, lambda: woken.append(1))) as c:
            return await c.call_tool("add_svg", args)

    ref = human(store, PAPER)
    args = {"page": ref["slug"], "svg": DOT, "alt": "d"}
    anyio.run(lambda: main(**args, dry_run=True))
    assert woken == []  # a dry run queues nothing
    anyio.run(lambda: main(**args, key="k"))
    assert woken == [1]
    anyio.run(lambda: main(**args, key="k"))
    assert woken == [1]  # a retry queues nothing either


def test_the_switch_hides_add_svg_and_a_bad_value_stops_the_start(
    store, monkeypatch, tmp_path
):
    assert "add_svg" in tools(store)
    assert "add_svg" in (mcp_server.server(store).instructions or "")
    for off in ("0", "false", "Off"):
        monkeypatch.setenv("SCRAP_MCP_UPLOAD", off)
        assert "add_svg" not in tools(store)
        assert "add_svg" not in (mcp_server.server(store).instructions or "")
    for bad in ("maybe", "", "  "):
        monkeypatch.setenv("SCRAP_MCP_UPLOAD", bad)
        with pytest.raises(SystemExit, match="SCRAP_MCP_UPLOAD"):
            mcp_server.server(store)
        with pytest.raises(SystemExit, match="SCRAP_MCP_UPLOAD"):
            create_app(tmp_path / "other")


# ---- the /mcp upload


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_MCP_TOKEN", SECRET)
    return TestClient(create_app(tmp_path / "data"))


def page_of(client, text=PAPER):
    r = client.post("/api/captures", json={"id": new_ulid(), "text": text})
    return r.json()


def upload(client, key, *files, headers=None, cid=None, **form):
    return client.post(
        f"/mcp/pages/{key}/captures",
        data={"id": cid or new_ulid(), **form},
        files=[("file", f) for f in files],
        headers=bearer(SECRET) if headers is None else headers,
    )


def test_the_upload_needs_the_bearer_and_is_claudes(client, tmp_path):
    ref = page_of(client)
    png = ("chart.png", b"\x89PNG not really", "image/png")
    assert upload(client, ref["page_id"], png, headers=LOCAL).status_code == 401
    wrong = {**LOCAL, "Authorization": "Bearer nope"}
    assert upload(client, ref["page_id"], png, headers=wrong).status_code == 401
    cid = new_ulid()
    r = upload(client, ref["page_id"], png, ("tri.svg", TRIANGLE, "image/svg+xml"),
               cid=cid, after="working.", alt="Q1 chart")  # fmt: skip
    assert r.status_code == 201, r.text
    page = r.json()
    shas = [a["sha256"] for a in page["added"]]
    assert [a["download_url"] for a in page["added"]] == [
        f"/mcp/blobs/{sha}?download=1" for sha in shas
    ]
    embeds = "\n\n".join(f"![Q1 chart](/api/blobs/{s}/preview?size=2048)" for s in shas)
    assert page["body"] == (
        f"Q1 Find the hypotenuse.\nShow your working.\n\n{embeds}\n\nQ2 Factorise 12."
    )
    added = page["captures"][1]
    assert (added["author"], added["source"]) == ("claude", "mcp")
    with closing(connect(Store(tmp_path / "data").db)) as conn:
        last = conn.execute(
            "SELECT author, source FROM page_rev WHERE page_id = ? AND rev = 2",
            (ref["page_id"],),
        ).fetchone()
    assert tuple(last) == ("claude", "mcp")
    hits = client.get("/api/search", params={"q": "is:claude-edited"}).json()
    assert [h["id"] for h in hits] == [ref["page_id"]]
    # the stored SVG was sanitised, and both download behind the bearer
    got = client.get(f"/mcp/blobs/{shas[1]}?download=1", headers=bearer(SECRET))
    assert got.status_code == 200 and got.content == svg.sanitise(TRIANGLE)
    # a retry with the same id changes nothing
    again = upload(client, ref["page_id"], png, cid=cid)
    assert again.status_code == 200 and again.json()["appended_on"] is None
    assert again.json()["rev"] == 2


def test_after_matches_with_crlf_line_ends(client):
    ref = page_of(client, "Q1 Find x.\nShow it.\n\nQ2")
    r = upload(client, ref["page_id"], ("a.png", b"x", "image/png"),
               after="Find x.\r\nShow it.")  # fmt: skip
    assert r.status_code == 201, r.text
    assert r.json()["body"].startswith("Q1 Find x.\nShow it.\n\n![](")


def test_the_upload_keeps_the_type_and_size_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_MCP_TOKEN", SECRET)
    monkeypatch.setenv("SCRAP_MAX_UPLOAD_MB", "0.01")  # about 10 KB
    client = TestClient(create_app(tmp_path / "small"))
    ref = page_of(client)
    zipped = upload(client, ref["page_id"], ("a.zip", b"PK", "application/zip"))
    assert zipped.status_code == 415
    big = upload(client, ref["page_id"], ("a.png", bytes(20_000), "image/png"))
    assert big.status_code == 413
    no_id = upload(client, ref["page_id"], ("a.png", b"x", "image/png"), cid="nope")
    assert no_id.status_code == 422
    assert client.get(f"/api/pages/{ref['page_id']}").json()["rev"] == 1


def test_the_upload_with_content_edit_off_takes_any_page_and_wakes_the_worker(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SCRAP_MCP_TOKEN", SECRET)
    monkeypatch.setenv("SCRAP_MCP_CONTENT_EDIT", "0")
    client = TestClient(create_app(tmp_path / "data"))
    woken = []
    client.app.state.worker = type(  # type: ignore[attr-defined]
        "W", (), {"wake": lambda self: woken.append(1), "alive": lambda self: True}
    )()
    ref = page_of(client)
    png = ("a.png", b"x", "image/png")
    before = len(woken)
    r = upload(client, ref["page_id"], png)
    assert r.status_code == 201 and r.json()["captures"][1]["author"] == "claude"
    assert len(woken) == before + 1
    # the PWA's own path is unchanged
    r = client.post(f"/api/pages/{ref['page_id']}/captures",
                    data={"id": new_ulid()}, files=[("file", png)])  # fmt: skip
    assert r.status_code == 201 and r.json()["captures"][-1]["author"] == "tagged"


def test_with_upload_off_there_is_no_route(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_MCP_TOKEN", SECRET)
    monkeypatch.setenv("SCRAP_MCP_UPLOAD", "0")
    client = TestClient(create_app(tmp_path / "data"))
    ref = page_of(client)
    r = upload(client, ref["page_id"], ("a.png", b"x", "image/png"))
    assert r.status_code in (404, 405)
    assert client.get(f"/api/pages/{ref['page_id']}").json()["rev"] == 1


def test_add_svg_says_where_the_image_went(store):
    ref = human(store, PAPER)
    args = {"page": ref["slug"], "svg": DOT, "alt": "d"}
    dry = ok(store, "add_svg", **args, after="hypotenuse.", dry_run=True)
    assert dry["placed"] == "after"
    assert ok(store, "add_svg", **args, dry_run=True)["placed"] is None  # no after
    table = human(store, "- a\n  | x | y |\n  |---|---|\n  | 1 | 2 |\n- b")
    out = ok(store, "add_svg", page=table["slug"], svg=DOT, alt="d", after="| 1 |")
    assert out["placed"] == "end"  # no place there kept the page: at the end
    assert store.page(table["slug"])["body"].endswith(f"- b\n\n{out['embed']}")


def test_the_upload_says_where_the_images_went(client):
    ref = page_of(client)
    r = upload(client, ref["page_id"], ("a.png", b"x", "image/png"), after="working.")
    assert r.status_code == 201 and r.json()["placed"] == "after"
    r = upload(client, ref["page_id"], ("b.png", b"y", "image/png"))
    assert r.json()["placed"] is None
