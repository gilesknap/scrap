"""Publishing a page through the PWA's API (PUT /api/pages/{key}/published, GET
/api/public, POST /api/public/rebuild) to the real receiver, and unpublishing it
however it stops being public (ADR 43; docs/reference/public-site.md)."""

import hashlib
import io
import threading
import time

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client
from PIL import Image

from publishhelp import SITE, Site, configure, page
from scrap import mcp_server
from scrap.app import create_app
from scrap.publish import files as publish_files
from scrap.publish import tag_key
from scrap.store import body_refs, new_ulid


@pytest.fixture
def site(tmp_path, monkeypatch):
    running = Site(tmp_path / "site")
    configure(monkeypatch, tmp_path, running)
    yield running
    running.stop()


@pytest.fixture
def app(tmp_path, site):
    return create_app(tmp_path / "data")


@pytest.fixture
def client(app):
    return TestClient(app)


def photo(colour: str | tuple[int, int, int] = "red", size=(400, 300)) -> bytes:
    im = Image.new("RGB", size, colour)
    exif = Image.Exif()
    exif[0x010F] = "Canon"  # Make
    exif[0x0110] = "EOS secret"  # Model
    out = io.BytesIO()
    im.save(out, "JPEG", exif=exif)
    return out.getvalue()


def made(client, text="Whiteboard\nnotes", files=(), tags=("work",)) -> dict:
    """A page, made public; its files' shas in body order."""
    data = {"id": new_ulid(), "text": text}
    sent = [("file", f) for f in files]
    if sent:
        ref = client.post("/api/captures", data=data, files=sent).json()
    else:
        ref = client.post("/api/captures", json=data).json()
    edit = {"tags": list(tags), "public": True}
    p = client.patch(f"/api/pages/{ref['slug']}", json=edit).json()
    return p


def shas(p: dict) -> list[str]:
    return [b["sha256"] for c in p["captures"] for b in c["blobs"]]


def chip(tag: str) -> str:
    from urllib.parse import quote

    return f'<a class="chip" href="scrap-tag:{quote(tag, safe="")}">{tag}</a>'


def put(client, p: dict, body: str, base_rev=None, defer=False, confirmed=True,
        **kw):  # fmt: skip
    html = page(body, title=p["title"], **kw)
    rev = p["rev"] if base_rev is None else base_rev
    ask = {"html": html, "base_rev": rev, "defer": defer}
    if confirmed is not None:
        ask["confirmed"] = confirmed
    return client.put(f"/api/pages/{p['slug']}/published", json=ask)


def test_publish_a_page_with_its_photo_and_tags(client, site, tmp_path):
    original = photo()
    p = made(client, files=[("board.jpg", original, "image/jpeg")])
    (sha,) = shas(p)
    body = (
        f'<h1>{p["title"]}</h1><figure><img src="scrap-blob:{sha}" alt="board.jpg">'
        f'</figure><p><a href="scrap-blob:{sha}">full size</a> {chip("work")}</p>'
    )
    r = put(client, p, body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["url"] == f"{SITE}/p/{p['slug']}"
    assert out["files"] == 1
    units = site.units()
    assert {f"p/{p['slug']}", "home", "pagefind", f"t/{tag_key('work')}"} <= set(units)
    index = site.file(f"p/{p['slug']}", "index.html").decode()
    assert "scrap-blob" not in index and "scrap-tag" not in index
    assert sha not in index  # the stored sha is never published
    names = sorted(f.name for f in (site.folder / "www" / "p" / p["slug"]).iterdir())
    image = f"/p/{p['slug']}/{names[0]}"
    assert index.count(f'"{image}"') == 2  # the img and the link to the same file
    assert f'href="/t/{tag_key("work")}"' in index
    published = site.file(f"p/{p['slug']}", names[0])
    # keyed by the slug: a name never shows a stored sha (the sha of its bytes)
    assert names[0] == f"img-1-{publish_files.file_hex(p['slug'], published)}.jpg"
    assert names[0][6:16] != hashlib.sha256(published).hexdigest()[:10]
    assert published != original  # never the original: its 2048-pixel preview
    im = Image.open(io.BytesIO(published))
    assert im.format == "JPEG" and not im.getexif()  # no EXIF (Make, Model, GPS)
    assert b"EOS secret" not in published
    home = site.file("home", "index.html").decode()
    assert f'href="/p/{p["slug"]}"' in home and "Whiteboard" in home
    # the page's API shows it, and the list has it
    got = client.get(f"/api/pages/{p['slug']}").json()
    assert got["public"] is True and got["published_at"] == out["published_at"]
    assert got["public_url"] == out["url"] and got["site"] == SITE
    listed = client.get("/api/public").json()
    assert listed == [{"id": p["id"], "slug": p["slug"], "title": p["title"],
                       "published_at": out["published_at"]}]  # fmt: skip
    kept = tmp_path / "data" / "cache" / "publish" / "p" / p["slug"]
    assert sorted(f.name for f in kept.iterdir()) == sorted([*names, "meta.json"])


def test_not_public_stale_and_trashed_are_409(client, note):
    ref = note("Private\nwords")
    p = client.get(f"/api/pages/{ref['slug']}").json()
    r = put(client, p, "<p>words</p>")
    assert (r.status_code, r.json()["error"]) == (409, "not_public")
    p = client.patch(f"/api/pages/{ref['slug']}", json={"public": True}).json()
    r = put(client, p, "<p>words</p>", base_rev=p["rev"] + 5)
    assert (r.status_code, r.json()["error"], r.json()["rev"]) == (
        409,
        "stale",
        p["rev"],
    )
    client.delete(f"/api/pages/{ref['slug']}")
    r = put(client, p, "<p>words</p>")
    assert (r.status_code, r.json()["error"]) == (409, "not_public")
    assert "trash" in r.json()["detail"]
    assert client.put("/api/pages/nope/published", json={
        "html": "x", "base_rev": 1}).status_code == 404  # fmt: skip


def test_a_first_publish_needs_confirmed(client, site):
    p = made(client)
    for confirmed in (None, False):
        r = put(client, p, "<p>notes</p>", confirmed=confirmed)
        assert (r.status_code, r.json()["error"]) == (409, "unconfirmed"), r.text
        assert "confirm" in r.json()["detail"]
    assert not any(u.startswith("p/") for u in site.units())  # nothing went out
    assert put(client, p, "<p>notes</p>").status_code == 200
    # a republish of a page with a kept copy needs no confirmation
    assert put(client, p, "<p>notes again</p>", confirmed=None).status_code == 200
    # unpublished (made private): the next publish is a first one again
    client.patch(f"/api/pages/{p['slug']}", json={"public": False})
    p = client.patch(f"/api/pages/{p['slug']}", json={"public": True}).json()
    r = put(client, p, "<p>notes</p>", confirmed=None)
    assert (r.status_code, r.json()["error"]) == (409, "unconfirmed")
    # not_public is checked first, under the same lock
    client.patch(f"/api/pages/{p['slug']}", json={"public": False})
    r = put(client, p, "<p>notes</p>", confirmed=None)
    assert (r.status_code, r.json()["error"]) == (409, "not_public")
    r = client.put(f"/api/pages/{p['slug']}/published",
                   json={"html": "x", "base_rev": 1, "confirmed": "yes"})  # fmt: skip
    assert (r.status_code, r.json()["error"]) == (422, "bad_request")


def test_a_render_that_raced_an_unpublish_is_refused_under_the_lock(client, app):
    """The lock is held over publish and unpublish, and publish reads the page again
    under it: a render that started before the page went private never puts it
    back."""
    p = made(client)
    publisher = app.state.publisher
    answers = []
    with publisher.lock:
        worker = threading.Thread(
            target=lambda: answers.append(put(client, p, "<p>notes</p>"))
        )
        worker.start()
        time.sleep(0.3)
        assert not answers  # waiting for the lock
        app.state.publisher.store.update_page(p["id"], None, None, None, "x",
                                              public=False)  # fmt: skip
    worker.join(10)
    assert (answers[0].status_code, answers[0].json()["error"]) == (409, "not_public")


def test_made_private_unpublishes_at_once(client, site, tmp_path):
    p = made(client, tags=("work", "board"))
    assert put(client, p, f"<p>notes</p>{chip('work')}").status_code == 200
    assert f"p/{p['slug']}" in site.units()
    out = client.patch(f"/api/pages/{p['slug']}", json={"public": False})
    assert out.status_code == 200 and "unpublish" not in out.json()
    assert out.json()["published_at"] is None and out.json()["public"] is False
    units = site.units()
    assert f"p/{p['slug']}" not in units
    assert f"t/{tag_key('work')}" not in units  # no public page has it now
    assert p["slug"] not in site.file("home", "index.html").decode()
    assert not (tmp_path / "data" / "cache" / "publish" / "p" / p["slug"]).exists()
    assert client.get("/api/public").json() == []


def test_private_while_the_site_is_down_is_pending_then_reconciled(
    client, app, site, tmp_path, monkeypatch
):
    p = made(client)
    assert put(client, p, "<p>notes</p>").status_code == 200
    monkeypatch.setenv("SCRAP_PUBLISH_TO", "http://127.0.0.1:9")  # nobody there
    out = client.patch(f"/api/pages/{p['slug']}", json={"public": False}).json()
    assert out["public"] is False and out["unpublish"] == "pending"
    assert out["published_at"] is None  # the copy went first
    assert f"p/{p['slug']}" in site.units()  # still on the site...
    monkeypatch.setenv("SCRAP_PUBLISH_TO", site.url)
    app.state.publisher.reconcile()
    assert f"p/{p['slug']}" not in site.units()  # ...until the next reconcile
    assert app.state.publisher.last["ok"] is True


def test_the_trash_unpublishes_and_undelete_keeps_the_flag(client, site):
    p = made(client)
    assert put(client, p, "<p>notes</p>").status_code == 200
    assert client.delete(f"/api/pages/{p['slug']}").status_code == 204
    assert f"p/{p['slug']}" not in site.units()
    back = client.post(f"/api/pages/{p['slug']}/undelete").json()
    assert back["public"] is True and back["published_at"] is None
    assert [x["published_at"] for x in client.get("/api/public").json()] == [None]
    # published again on the next render, without being made public again
    assert put(client, back, "<p>notes</p>").status_code == 200


def mcp(app, tool: str, **args):
    store = app.state.publisher.store

    async def main():
        server = mcp_server.server(store, publisher=app.state.publisher)
        async with Client(server) as c:
            return await c.call_tool(tool, args)

    result = anyio.run(main)
    assert not result.is_error, result.content
    return result.structured_content


def test_mcp_private_revert_and_trash_unpublish(client, app, site):
    a, b, c = made(client, "A\nx"), made(client, "B\ny"), made(client, "C\nz")
    for p in (a, b, c):
        assert put(client, p, "<p>x</p>").status_code == 200
    read = mcp(app, "read", page=a["slug"])["page"]
    assert read["public"] is True and read["public_url"] == f"{SITE}/p/{a['slug']}"
    assert read["published_at"] is not None
    out = mcp(app, "edit_meta", pages=[a["slug"]], public=False)
    assert "unpublish" not in out and f"p/{a['slug']}" not in site.units()
    # a revert that turns the flag off unpublishes too (the flag revision of b)
    revs = mcp(app, "revisions", page=b["slug"])["meta"]
    flag = next(r for r in revs if not r["public_before"] and r["public_after"])
    mcp(app, "revert", revision=flag["id"])
    assert f"p/{b['slug']}" not in site.units()
    mcp(app, "trash_pages", pages=[c["slug"]])
    assert not any(u.startswith("p/") for u in site.units())
    assert client.get("/api/public").json() == []


def test_mcp_edit_meta_makes_one_page_public_at_a_time(client, app, note):
    one, two = note("One\na"), note("Two\nb")
    store = app.state.publisher.store

    async def main():
        async with Client(mcp_server.server(store)) as c:
            return await c.call_tool(
                "edit_meta", {"pages": [one["slug"], two["slug"]], "public": True}
            )

    result = anyio.run(main)
    assert result.is_error and "one at a time" in result.content[0].text  # type: ignore[union-attr]
    assert mcp(app, "edit_meta", pages=[one["slug"]], public=True)["changed"] == 1
    assert mcp(app, "edit_meta", pages=[two["slug"]], public=True)["changed"] == 1
    out = mcp(app, "edit_meta", pages=[one["slug"], two["slug"]], public=False)
    assert out["changed"] == 2 and out["batch"]  # private works in bulk
    # made public over MCP, never rendered: "not published yet" until the app does
    mcp(app, "edit_meta", pages=[one["slug"]], public=True)
    assert mcp(app, "read", page=one["slug"])["page"]["published_at"] is None


def test_the_page_keeps_its_files_and_links(client, site):
    pdf = b"%PDF-1.4\n%secret original\n"
    p = made(client, files=[("a.jpg", photo(), "image/jpeg"),
                            ("report.pdf", pdf, "application/pdf")])  # fmt: skip
    img, doc = shas(p)
    body = p["body"] + f"\n\n[report.pdf](/api/blobs/{doc})"
    p = client.patch(f"/api/pages/{p['slug']}",
                     json={"base_rev": p["rev"], "body": body}).json()  # fmt: skip
    other = made(client, "Other\npage")
    body = p["body"] + f"\n\nSee [[{other['slug']}]]."
    p = client.patch(f"/api/pages/{p['slug']}",
                     json={"base_rev": p["rev"], "body": body}).json()  # fmt: skip
    html = (
        f'<p><a href="scrap-blob:{doc}">report.pdf</a>'
        f'<img src="scrap-blob:{img}" alt="a.jpg">'
        f'<a href="/p/{other["slug"]}">other</a></p>'
    )
    r = put(client, p, html)
    assert r.status_code == 200, r.text
    assert r.json()["files"] == 2
    folder = site.folder / "www" / "p" / p["slug"]
    names = sorted(f.name for f in folder.iterdir())
    assert names[0].startswith("file-1-") and names[0].endswith(".pdf")
    assert names[1].startswith("img-1-") and names[1].endswith(".jpg")
    assert (folder / names[0]).read_bytes() == pdf  # a file goes out as stored
    assert doc[:10] not in names[0]  # so its name is keyed: never the stored sha
    assert names[0] == f"file-1-{publish_files.file_hex(p['slug'], pdf)}.pdf"
    # links_to: the pages whose published copy refers to a page
    linking = client.get(f"/api/public?links_to={other['slug']}").json()
    assert [x["slug"] for x in linking] == [p["slug"]]
    assert client.get("/api/public?links_to=nothing").json() == []


def test_a_file_attached_to_the_page_is_on_it(client, site):
    """The page's own captures' files (listed below its text) count as on the page,
    though its text does not refer to them."""
    pdf = b"%PDF-1.4\n%attached\n"
    p = made(client, files=[("report.pdf", pdf, "application/pdf")])
    (doc,) = shas(p)
    assert doc not in body_refs(p["body"])  # its text does not name it
    r = put(client, p, f'<p><a href="scrap-blob:{doc}">report.pdf</a></p>')
    assert r.status_code == 200, r.text
    folder = site.folder / "www" / "p" / p["slug"]
    (name,) = [f.name for f in folder.iterdir() if f.name.startswith("file-")]
    assert (folder / name).read_bytes() == pdf


def test_a_link_to_a_private_page_still_counts_for_links_to(client, note):
    """A private page's link is a label on the site; when that page goes public, the
    PWA finds the pages to render again by links_to."""
    hidden = note("Hidden\nh")
    p = made(client, f"Linker\nsee [[{hidden['slug']}]]")
    assert put(client, p, "<p>see <span>Hidden</span></p>").status_code == 200
    linking = client.get(f"/api/public?links_to={hidden['slug']}").json()
    assert [x["slug"] for x in linking] == [p["slug"]]


def test_an_svg_is_sanitised_again(client, site, app):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5"/></svg>'
    p = made(client, files=[("d.svg", svg, "image/svg+xml")])
    (sha,) = shas(p)
    path, _ = app.state.publisher.store.blob(sha)  # as one stored before #480
    path.write_bytes(
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5"'
        b' onclick="alert(1)"/><script>alert(2)</script></svg>'
    )
    r = put(client, p, f'<p><img src="scrap-blob:{sha}" alt="d"></p>')
    assert r.status_code == 200, r.text
    folder = site.folder / "www" / "p" / p["slug"]
    (name,) = [f.name for f in folder.iterdir() if f.name != "index.html"]
    assert name.startswith("img-1-") and name.endswith(".svg")
    published = (folder / name).read_bytes()
    assert b"<rect" in published and b"onclick" not in published
    assert b"script" not in published


def refusal(r, code: str) -> str:
    assert (r.status_code, r.json()["error"]) == (422, code), r.text
    return r.json()["detail"]


def test_placeholders_must_name_files_on_the_page(client, app):
    p = made(client, files=[("a.jpg", photo(), "image/jpeg")])
    (sha,) = shas(p)
    other = made(client, "Other\nx", files=[("b.jpg", photo("blue"), "image/jpeg")])
    (theirs,) = shas(other)
    refusal(put(client, p, f'<img src="scrap-blob:{theirs}" alt="">'),
            "bad_placeholder")  # fmt: skip
    refusal(
        put(client, p, f'<img src="scrap-blob:{"0" * 64}" alt="">'), "bad_placeholder"
    )
    pdf = made(client, "Doc\nx", files=[("r.pdf", b"%PDF-1.4", "application/pdf")])
    (doc,) = shas(pdf)
    body = pdf["body"] + f"\n[r](/api/blobs/{doc})"
    pdf = client.patch(f"/api/pages/{pdf['slug']}",
                       json={"base_rev": pdf["rev"], "body": body}).json()  # fmt: skip
    assert "not an image" in refusal(
        put(client, pdf, f'<img src="scrap-blob:{doc}" alt="">'), "bad_placeholder"
    )
    assert put(client, p, f'<img src="scrap-blob:{sha}" alt="">').status_code == 200


def test_stale_tags_and_a_failed_check(client):
    p = made(client, tags=("work",))
    refusal(put(client, p, chip("gone")), "stale_tags")
    assert "script" in refusal(put(client, p, "<script>x</script>"), "bad_html")


def test_the_caps(client, monkeypatch):
    many = [
        (f"{n}.jpg", photo((n * 9, 0, 0), (40, 30)), "image/jpeg") for n in range(21)
    ]
    p = made(client, files=many)
    imgs = "".join(f'<img src="scrap-blob:{s}" alt="">' for s in shas(p))
    assert "at most 20" in refusal(put(client, p, imgs), "too_many_files")
    first = "".join(f'<img src="scrap-blob:{s}" alt="">' for s in shas(p)[:20])
    monkeypatch.setattr(publish_files, "MAX_FILE", 100)  # a preview is bigger
    refusal(put(client, p, first), "file_too_large")
    monkeypatch.setattr(publish_files, "MAX_FILE", 20 * 2**20)
    monkeypatch.setattr(publish_files, "MAX_UNIT", 2000)
    refusal(put(client, p, first), "unit_too_large")
    monkeypatch.setattr(publish_files, "MAX_UNIT", 200 * 2**20)
    assert put(client, p, first).status_code == 200


def test_a_body_over_25_mib_is_413(client):
    p = made(client)
    r = client.put(f"/api/pages/{p['slug']}/published",
                   content=b"x" * (25 * 2**20 + 1),
                   headers={"Content-Type": "application/json"})  # fmt: skip
    assert (r.status_code, r.json()["error"]) == (413, "too_large")
    r = client.put(f"/api/pages/{p['slug']}/published", content=b"{nope")
    assert (r.status_code, r.json()["error"]) == (422, "bad_request")


def test_deferred_then_rebuilt(client, site):
    a, b = made(client, "A\nx"), made(client, "B\ny")
    assert put(client, a, "<p>x</p>", defer=True).status_code == 200
    assert put(client, b, "<p>y</p>", defer=True).status_code == 200
    assert set(site.units()) == {f"p/{a['slug']}", f"p/{b['slug']}"}
    r = client.post("/api/public/rebuild")
    assert r.status_code == 200
    assert {"home", "pagefind", "assets", f"t/{tag_key('work')}"} <= set(
        r.json()["units"]
    )
    assert client.post("/api/public/rebuild").json() == {"units": []}  # unchanged


def test_a_receiver_refusal_is_502(client, tmp_path, monkeypatch):
    tiny = Site(tmp_path / "tiny", quota=4096)  # room for one small file
    try:
        configure(monkeypatch, tmp_path, tiny)
        p = made(client, files=[("a.jpg", photo(), "image/jpeg")])
        (sha,) = shas(p)
        r = put(client, p, f'<img src="scrap-blob:{sha}" alt="">')
        assert (r.status_code, r.json()) == (
            502, {"error": "publish_failed", "detail": "over_quota"}
        )  # fmt: skip
        assert client.get(f"/api/pages/{p['slug']}").json()["published_at"] is None
    finally:
        tiny.stop()


def test_not_configured_is_503(tmp_path, monkeypatch, note):
    monkeypatch.delenv("SCRAP_PUBLISH_TO")
    c = TestClient(create_app(tmp_path / "off"))
    ref = c.post("/api/captures", json={"id": new_ulid(), "text": "T\nx"}).json()
    p = c.patch(f"/api/pages/{ref['slug']}", json={"public": True}).json()
    r = put(c, p, "<p>x</p>")
    assert (r.status_code, r.json()["error"]) == (503, "not_configured")
    assert c.post("/api/public/rebuild").status_code == 503
    assert c.get("/healthz").json()["publish"]["enabled"] is False
    # the flag still works without a site
    assert (
        c.patch(f"/api/pages/{ref['slug']}", json={"public": False}).status_code == 200
    )


def test_health_has_a_publish_block_that_never_fails(client, app, site):
    made(client)
    app.state.publisher.reconcile()
    h = client.get("/healthz").json()
    assert h["status"] == "ok"
    assert h["publish"]["enabled"] is True and h["publish"]["ok"] is True
    assert h["publish"]["site"] == SITE
    assert client.get("/api/health").json()["publish"]["enabled"] is True
    site.stop()
    app.state.publisher.reconcile()  # the site is down
    h = client.get("/healthz")
    assert h.status_code == 200 and h.json()["publish"]["ok"] is False
    assert "unreachable" in h.json()["publish"]["error"]


def test_no_mcp_route_publishes(client):
    routes = [r for r in client.app.routes if "published" in getattr(r, "path", "")]
    assert [(r.path, sorted(r.methods)) for r in routes] == [
        ("/api/pages/{key}/published", ["PUT"])
    ]
    assert all(not getattr(r, "path", "").startswith("/mcp") or "publish" not in
               getattr(r, "path", "") for r in client.app.routes)  # fmt: skip


def test_bad_settings_stop_the_start(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_PUBLISH_TO", "ftp://x")
    with pytest.raises(SystemExit):
        create_app(tmp_path / "a")
    monkeypatch.setenv("SCRAP_PUBLISH_TO", "http://127.0.0.1:9")
    short = tmp_path / "short"
    short.write_text("too short")
    monkeypatch.setenv("SCRAP_PUBLISH_TOKEN_FILE", str(short))
    with pytest.raises(SystemExit):
        create_app(tmp_path / "b")
    monkeypatch.setenv("SCRAP_PUBLISH_TOKEN_FILE", str(tmp_path / "missing"))
    with pytest.raises(SystemExit):
        create_app(tmp_path / "c")


def test_the_reconcile_loop_runs_from_the_lifespan(tmp_path, site):
    with TestClient(create_app(tmp_path / "data")) as c:
        deadline = time.monotonic() + 30
        while c.app.state.publisher.last["at"] is None:  # type: ignore[attr-defined]
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert {"home", "pagefind", "assets"} <= set(site.units())
    assert c.app.state.publisher._thread is None  # type: ignore[attr-defined]


def test_no_loop_without_publishing(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as c:
        assert c.app.state.publisher._thread is None  # type: ignore[attr-defined]


def test_a_tag_with_an_apostrophe_publishes(client, site):
    """The publish mode writes a tag with encodeURIComponent, which leaves ' ( ) ! *
    as they are."""
    tag = "it's (fun)!*"
    p = made(client, tags=(tag,))
    r = put(client, p, f'<p><a class="chip" href="scrap-tag:it\'s%20(fun)!*">x</a></p>')
    assert r.status_code == 200, r.text
    index = site.file(f"p/{p['slug']}", "index.html").decode()
    assert f'href="/t/{tag_key(tag)}"' in index and "scrap-tag" not in index
    assert f"t/{tag_key(tag)}" in site.units()
    assert "it&#x27;s (fun)!*" in site.file(f"t/{tag_key(tag)}", "index.html").decode()
