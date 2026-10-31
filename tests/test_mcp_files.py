"""Downloads for MCP clients under /mcp/... (#479): the /api handlers, behind the
MCP bearer token; the browser's /api paths unchanged."""

import io
import json
import zipfile
from urllib.parse import urlsplit

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from scrap import ingest, mcp_files
from scrap.app import create_app
from scrap.drawing import excalidraw_file
from scrap.store import Store, new_ulid
from test_ingest import BOARD, Fake, jpeg
from test_mcp import LOCAL, SECRET, bearer, ok

BASE = "https://scrap.example.ts.net:8446"


@pytest.fixture
def drawn(tmp_path, monkeypatch):
    """With a token set: (client, the photo's sha, its capture id, the page id) for
    a photo page Claude (faked) has drawn, and a text file beside it."""
    monkeypatch.setenv("SCRAP_PUBLIC_URL", BASE)
    monkeypatch.setenv("SCRAP_MCP_TOKEN", SECRET)
    client = TestClient(create_app(tmp_path))
    files = [
        ("file", ("board.jpg", jpeg(size=(800, 600)), "image/jpeg")),
        ("file", ("notes.txt", b"hello", "text/plain")),
    ]
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
    assert ingest.Worker(Store(tmp_path), Fake(BOARD)).step()
    page = client.get(f"/api/pages/{ref['page_id']}").json()
    sha = page["captures"][0]["blobs"][0]["sha256"]
    return client, sha, ref["capture_id"], ref["page_id"]


def paths(sha, cid, page):
    """Every mirrored GET, as /api paths."""
    return [
        f"/api/blobs/{sha}",
        f"/api/blobs/{sha}?download=1",
        f"/api/blobs/{sha}/preview?size=480",
        f"/api/blobs/{sha}/uses?page={page}",
        f"/api/pages/{page}/download",
        f"/api/pages/{page}/download?notes=0&photos=preview",
        f"/api/captures/{cid}/photos/{sha}/drawing",
        f"/api/captures/{cid}/photos/{sha}/drawing/versions",
    ]


def same(a, b):
    """The same reply: status, type, disposition and content (a zip's entries)."""
    assert a.status_code == b.status_code == 200
    for header in ("content-type", "content-disposition"):
        assert a.headers.get(header) == b.headers.get(header)
    if a.headers["content-type"] == "application/zip":
        za, zb = (zipfile.ZipFile(io.BytesIO(r.content)) for r in (a, b))
        assert za.namelist() == zb.namelist()
        assert all(za.read(n) == zb.read(n) for n in za.namelist())
    else:
        assert a.content == b.content


def test_each_download_needs_the_bearer_and_matches_the_api(drawn):
    client, sha, cid, page = drawn
    for path in paths(sha, cid, page):
        mcp = path.replace("/api/", "/mcp/", 1)
        refused = client.get(mcp, headers=LOCAL)
        assert refused.status_code == 401, mcp
        assert refused.headers["WWW-Authenticate"] == "Bearer"
        wrong = client.get(mcp, headers={**LOCAL, "Authorization": "Bearer nope"})
        assert wrong.status_code == 401, mcp
        # the browser's path, with no bearer, is as it was
        same(client.get(mcp, headers=bearer(SECRET)), client.get(path, headers=LOCAL))


def test_the_drawing_downloads_whole_as_an_excalidraw_file(drawn):
    client, sha, cid, _ = drawn
    url = f"/mcp/captures/{cid}/photos/{sha}/drawing.excalidraw"
    assert client.get(url, headers=LOCAL).status_code == 401
    r = client.get(url, headers=bearer(SECRET))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.excalidraw+json"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith(
        'attachment; filename="board.excalidraw"'
    )
    current = client.get(f"/api/captures/{cid}/photos/{sha}/drawing").json()
    assert r.content == excalidraw_file(current["data"])
    assert json.loads(r.content)["type"] == "excalidraw"
    # not mirrored on /api: the browser's drawing routes are unchanged
    assert client.get(url.replace("/mcp/", "/api/", 1)).status_code == 404


def test_no_drawing_or_file_is_a_404(drawn):
    client, sha, cid, _ = drawn
    other = "00" * 32
    for url in (
        f"/mcp/blobs/{other}",
        f"/mcp/captures/{cid}/photos/{other}/drawing",
        f"/mcp/captures/{cid}/photos/{other}/drawing.excalidraw",
        "/mcp/pages/no-such-page/download",
    ):
        assert client.get(url, headers=bearer(SECRET)).status_code == 404, url


def test_downloads_keep_the_host_check_and_need_no_origin(drawn):
    client, sha, *_ = drawn
    url = f"/mcp/blobs/{sha}"
    auth = {"Authorization": f"Bearer {SECRET}"}
    assert client.get(url, headers={"Host": "evil.example"}).status_code == 401
    assert client.get(url, headers={"Host": "evil.example", **auth}).status_code == 421
    public = {"Host": urlsplit(BASE).netloc, **auth}
    assert client.get(url, headers=public).status_code == 200  # curl: no Origin


def test_without_a_token_downloads_are_open_as_mcp_is(tmp_path):
    client = TestClient(create_app(tmp_path))
    text = b"hello " * 1000
    files = [("file", ("a.txt", text, "text/plain"))]
    ref = client.post("/api/captures", data={"id": new_ulid()}, files=files).json()
    sha = client.get(f"/api/pages/{ref['page_id']}").json()["captures"][0]["blobs"]
    r = client.get(
        f"/mcp/blobs/{sha[0]['sha256']}", headers={"Accept-Encoding": "gzip"}
    )
    assert r.status_code == 200 and r.content == text
    assert "content-encoding" not in r.headers  # a file, as on /api: not gzipped


def test_downloads_leave_mcp_itself_alone(drawn):
    client, *_ = drawn
    init = {"protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"}}  # fmt: skip
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": init}
    accept = {"Accept": "application/json, text/event-stream"}
    with client:  # the MCP session manager runs in the app's lifespan
        r = client.post("/mcp", json=body, headers={**bearer(SECRET), **accept})
    assert r.status_code == 200


def test_tools_give_download_urls_that_serve(drawn, tmp_path):
    client, sha, cid, page = drawn
    store = Store(tmp_path)
    got = ok(store, "read", page=page)
    image, file = got["images"][0], got["files"][0]
    assert image["url"] == f"{BASE}/api/blobs/{sha}"  # the browser's, as before
    assert image["download_url"] == f"{BASE}/mcp/blobs/{sha}?download=1"
    drawing = f"{BASE}/mcp/captures/{cid}/photos/{sha}/drawing.excalidraw"
    assert image["drawing_download_url"] == drawing
    assert file["drawing_download_url"] is None
    assert got["page"]["download_url"] == f"{BASE}/mcp/pages/{page}/download"
    [row] = ok(store, "search")["results"]
    assert row["image_download_url"] == image["download_url"]
    assert ok(store, "drawing", page=page)["download_url"] == drawing
    for url in (image["download_url"], file["download_url"], drawing,
                got["page"]["download_url"]):  # fmt: skip
        assert fetch(client, url).status_code == 200
    saved = fetch(client, file["download_url"])
    assert saved.content == b"hello"
    # download=1: `curl -OJ` saves it under its own name
    assert 'filename="notes.txt"' in saved.headers["content-disposition"]


def fetch(client, url):
    """GET a tool's URL (its path and query) with the bearer token."""
    parts = urlsplit(url)
    return client.get(f"{parts.path}?{parts.query}", headers=bearer(SECRET))


def test_a_trashed_page_gives_no_page_or_drawing_download(drawn, tmp_path):
    client, sha, cid, page = drawn
    assert client.delete(f"/api/pages/{page}").status_code == 204
    got = ok(Store(tmp_path), "read", page=page)
    assert got["page"]["trashed"] and got["page"]["download_url"] is None
    image = got["images"][0]
    assert image["drawing_download_url"] is None
    # what they would have been are 404s, as on /api; the file itself still serves
    for url in (f"/mcp/pages/{page}/download",
                f"/mcp/captures/{cid}/photos/{sha}/drawing.excalidraw"):  # fmt: skip
        assert client.get(url, headers=bearer(SECRET)).status_code == 404
    assert fetch(client, image["download_url"]).status_code == 200


@pytest.mark.parametrize("method", ["put", "post", "delete", "patch"])
def test_downloads_take_no_writes(drawn, method):
    client, sha, cid, page = drawn
    for url in (
        f"/mcp/blobs/{sha}",
        f"/mcp/pages/{page}/download",
        f"/mcp/captures/{cid}/photos/{sha}/drawing",
        f"/mcp/captures/{cid}/photos/{sha}/drawing.excalidraw",
    ):
        r = client.request(method, url, headers=bearer(SECRET), json={})
        assert r.status_code == 405, (method, url)
        assert client.request(method, url, headers=LOCAL).status_code == 401
    # the drawing is as it was
    current = client.get(f"/api/captures/{cid}/photos/{sha}/drawing").json()
    assert current["version"] == 1


def test_downloads_under_a_root_path(drawn):
    client, sha, *_ = drawn
    rooted = TestClient(client.app, root_path="/scrap")
    url = f"/scrap/mcp/blobs/{sha}"
    assert rooted.get(url, headers=LOCAL).status_code == 401
    r = rooted.get(url, headers=bearer(SECRET))
    assert r.status_code == 200 and r.content == client.get(f"/api/blobs/{sha}").content


def test_a_missing_route_to_mirror_stops_scrap(tmp_path):
    with pytest.raises(RuntimeError, match="no GET route"):
        mcp_files.add_routes(FastAPI(), Store(tmp_path))


def stubs(**extra):
    """An app with every mirrored GET as a stub; extra goes to the first one's."""
    app = FastAPI()
    for n, path in enumerate(mcp_files.MIRRORED):
        app.get(path, **(extra if n == 0 else {}))(lambda: {})
    return app


@pytest.mark.parametrize(
    "extra", [{"dependencies": [Depends(lambda: None)]}, {"status_code": 202}]
)
def test_a_route_the_mirror_would_not_copy_faithfully_stops_scrap(tmp_path, extra):
    mcp_files.add_routes(stubs(), Store(tmp_path))  # plain routes mirror
    with pytest.raises(RuntimeError, match="dependencies or a status code"):
        mcp_files.add_routes(stubs(**extra), Store(tmp_path))
