"""The MCP server (#37): its tools, called in process, and /mcp over ASGI."""

import json
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client

from scrap import mcp_server
from scrap.app import create_app
from scrap.store import Store, new_ulid

ACCEPT = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.migrate()
    return s


def human(store, text="Shopping list\nmilk and eggs", **extra):
    """A page the user made, as the PWA does."""
    c = store.prepare({"id": new_ulid(), "text": text, **extra}, [])
    return store.capture(c, [], "giles@example.com")[0]


def call(store, tool: str, **args: Any) -> tuple[bool, Any]:
    """Call a tool in process: (is_error, structured result or the error text)."""

    async def main():
        async with Client(mcp_server.server(store)) as client:
            return await client.call_tool(tool, args)

    result = anyio.run(main)
    if result.is_error:
        return True, result.content[0].text  # type: ignore[union-attr]
    return False, result.structured_content


def ok(store, tool: str, **args: Any) -> Any:
    error, out = call(store, tool, **args)
    assert not error, out
    return out


def refused(store, tool: str, **args: Any) -> str:
    error, out = call(store, tool, **args)
    assert error, out
    return out


def write(store, **args: Any) -> dict[str, Any]:
    return ok(store, "write", **{"title": "T", "body": "B", "origin": "o", **args})


def test_tools_are_listed(store):
    async def main():
        async with Client(mcp_server.server(store)) as client:
            return [t.name for t in (await client.list_tools()).tools]

    tools = anyio.run(main)
    assert sorted(tools) == ["read", "recent", "search", "tags", "todos", "write"]


def test_write_makes_a_claude_page_with_provenance(store, monkeypatch):
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://scrap.example.ts.net:8446")
    out = write(
        store,
        title="  Findings  on\tMCP ",
        body="# Hi\n\nSome *findings*.",
        tags=["#Tech", "tech", "Claude Code"],
        kind="todo",
        status="in_progress",
        origin="homebase 2026-10-20",
    )
    assert out["created"] is True
    assert out["url"] == f"https://scrap.example.ts.net:8446/p/{out['slug']}"
    page = store.page(out["id"])
    assert page["title"] == "Findings on MCP"
    assert page["kind"] == "todo" and page["kind_fixed"] == 1
    assert page["fields"] == {"status": "in_progress", "origin": "homebase 2026-10-20"}
    assert sorted(page["tags"]) == ["claude code", "tech"]
    assert [(c["source"], c["author"]) for c in page["captures"]] == [("mcp", "claude")]
    with store.connect() as conn:
        assert store.by_claude(conn, out["id"])
        author = conn.execute(
            "SELECT author FROM page_rev WHERE page_id = ?", (out["id"],)
        ).fetchone()[0]
    assert author == "claude"


def test_write_kinds_take_the_pwa_names(store):
    assert store.page(write(store, kind="read")["id"])["kind"] == "consume"
    assert store.page(write(store, kind="board")["id"])["kind"] == "whiteboard"
    assert store.page(write(store)["id"])["kind"] == "note"
    assert "kind must be" in refused(
        store, "write", title="T", body="", origin="", kind="memory"
    )
    assert "status is for" in refused(
        store, "write", title="T", body="", origin="", status="open"
    )
    assert "status is for" in refused(
        store, "write", title="T", body="", origin="", kind="todo", status="later"
    )


def test_is_claude_finds_only_claude_pages(store):
    human(store, "my own findings")
    mine = write(store, title="Claude findings", body="findings")
    hits = ok(store, "search", query="findings is:claude")["results"]
    assert [h["id"] for h in hits] == [mine["id"]]
    others = ok(store, "search", query="findings -is:claude")["results"]
    assert len(others) == 1 and others[0]["id"] != mine["id"]


def test_a_retry_with_the_same_key_adds_nothing(store):
    first = write(store, key="session-1/post-1", title="Once")
    again = write(store, key="session-1/post-1", title="Once")
    assert again == {**first, "created": False}
    assert len(store.recent(10)) == 1
    other = write(store, key="session-1/post-2", title="Twice")
    assert other["id"] != first["id"]


def test_append_to_a_claude_page(store):
    page = write(store, title="Log", body="first", tags=["a"])
    out = write(
        store, append_to=page["slug"], body="## Later\n\nsecond", tags=["b"], key="k1"
    )
    assert out["id"] == page["id"] and out["created"] is True
    assert write(store, append_to=page["id"], body="x", key="k1")["created"] is False
    p = store.page(page["id"])
    assert p["body"] == "first\n\n## Later\n\nsecond"
    assert sorted(p["tags"]) == ["a", "b"] and p["rev"] == 2
    assert p["title"] == "Log"


def test_human_pages_are_never_changed(store):
    ref = human(store, "my notes")
    for key in (ref["page_id"], ref["slug"]):
        error = refused(store, "write", title="", body="more", origin="", append_to=key)
        assert "only a page written over MCP" in error
    page = store.page(ref["page_id"])
    assert page["body"] == "my notes" and page["rev"] == 1
    assert "no such page" in refused(
        store, "write", title="", body="x", origin="", append_to="nope"
    )


def test_a_client_cannot_claim_mcp_provenance_over_http(tmp_path):
    client = TestClient(create_app(tmp_path / "data"))
    r = client.post(
        "/api/captures", json={"id": new_ulid(), "text": "x", "source": "mcp"}
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    "args, error",
    [
        ({"title": "x" * 201}, "200"),
        ({"title": "   "}, "title must not be empty"),
        ({"body": "x" * 200_001}, "body is over"),
        ({"body": "é" * 100_001}, "body is over"),  # bytes, not characters
        ({"tags": [str(n) for n in range(21)]}, "20"),
        ({"tags": ["x" * 65]}, "1 to 64"),
        ({"tags": ["#"]}, "1 to 64"),
        ({"origin": "o" * 201}, "200"),
        ({"key": "k" * 129}, "128"),
        ({"body": "bad \ud800 text"}, "nicode"),  # ours, or pydantic's
        ({"title": "bad \udfff"}, "nicode"),  # ours, or pydantic's
        ({"tags": ["\ud83d"]}, "nicode"),  # ours, or pydantic's
        ({"body": "nul \x00"}, "NUL"),
    ],
)
def test_write_checks_sizes(store, args, error):
    message = refused(
        store, "write", **{"title": "T", "body": "B", "origin": "o", **args}
    )
    assert error in message
    assert store.recent(10) == []


def test_append_keeps_a_page_under_its_limit(store, monkeypatch):
    monkeypatch.setattr(mcp_server, "MAX_PAGE", 100)
    page = write(store, body="x" * 60)
    assert "over 100 bytes" in refused(
        store, "write", title="", body="y" * 60, origin="", append_to=page["id"]
    )


def test_search_passes_the_query_syntax_through(store):
    write(store, title="Alpha plan", body="the alpha project", tags=["work/alpha"])
    write(store, title="Beta plan", body="the beta project", kind="todo")
    human(store, "alpha in a human note")
    hits = ok(store, "search", query="plan")["results"]
    assert {h["title"] for h in hits} == {"Alpha plan", "Beta plan"}
    hit = ok(store, "search", query='"alpha project" tag:alpha')["results"]
    assert [h["title"] for h in hit] == ["Alpha plan"]
    assert hit[0]["tags"] == ["work/alpha"] and hit[0]["updated_at"]
    assert hit[0]["kind"] == "note" and hit[0]["url"].startswith("/p/")
    assert "<mark>" not in hit[0]["snippet"] and "alpha" in hit[0]["snippet"]
    assert [h["title"] for h in ok(store, "search", query="kind:todo")["results"]] == [
        "Beta plan"
    ]
    assert [h["title"] for h in ok(store, "search", query="plan -beta")["results"]] == [
        "Alpha plan"
    ]
    assert ok(store, "search", query="alpha after:2000-01-01")["results"]
    assert ok(store, "search", query="alpha before:2000-01-01")["results"] == []


def test_search_pages_with_limit_and_offset(store):
    for n in range(5):
        write(store, title=f"Page {n}", body="common")
    first = ok(store, "search", query="common", limit=2)["results"]
    rest = ok(store, "search", query="common", limit=10, offset=2)["results"]
    assert len(first) == 2 and len(rest) == 3
    assert not {h["id"] for h in first} & {h["id"] for h in rest}


def test_snippets_are_plain_text(store):
    write(store, title="Tags", body="use <b>bold</b> & more")
    [hit] = ok(store, "search", query="bold")["results"]
    assert "<b>bold</b> & more" in hit["snippet"]


def test_read_returns_the_text_as_data(store):
    target = human(store, "Target page")
    page = write(
        store,
        title="Reader",
        body=f"See [[{target['slug']}|it]] and [[missing]].",
        tags=["x"],
        origin="repo 2026-10-20",
    )
    linker = write(store, title="Linker", body=f"back to [[{page['slug']}]]")
    out = ok(store, "read", page=page["slug"])
    assert out["content"] == {
        "title": "Reader",
        "summary": None,
        "body_markdown": f"See [[{target['slug']}|it]] and [[missing]].",
    }
    meta = out["page"]
    assert meta["id"] == page["id"] and meta["written_by_claude"] is True
    assert meta["origin"] == "repo 2026-10-20" and meta["tags"] == ["x"]
    assert meta["rev"] == 1 and meta["kind"] == "note"
    assert [x["slug"] for x in out["links"]] == [target["slug"], "missing"]
    assert [b["id"] for b in out["backlinks"]] == [linker["id"]]
    assert out["images"] == []
    assert ok(store, "read", page=target["page_id"])["page"]["written_by_claude"] is (
        False
    )


def test_read_lists_images_as_urls(store, monkeypatch):
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://h.example:8446")
    sha = "ab" * 32
    c = store.prepare({"id": new_ulid()}, ["image/png"])
    ref = store.capture(c, [(sha, "image/png", 3, "a.png")], "me")[0]
    [image] = ok(store, "read", page=ref["page_id"])["images"]
    assert image["url"] == f"https://h.example:8446/api/blobs/{sha}"
    assert image["filename"] == "a.png" and image["has_drawing"] is False


def test_read_of_a_missing_or_trashed_page(store):
    page = write(store)
    store.delete_page(page["id"])
    assert "no such page" in refused(store, "read", page=page["id"])


def test_recent_and_todos(store):
    write(store, title="Note one")
    todo = write(store, title="Do it", kind="todo")
    done = write(store, title="Done it", kind="todo", status="done")
    write(store, title="Going", kind="todo", status="in_progress")
    titles = [r["title"] for r in ok(store, "recent")["results"]]
    assert titles == ["Going", "Done it", "Do it", "Note one"]
    assert len(ok(store, "recent", limit=1)["results"]) == 1
    assert [r["title"] for r in ok(store, "recent", kind="todo")["results"]] == [
        "Going",
        "Done it",
        "Do it",
    ]
    open_ = ok(store, "todos")["results"]
    assert {r["title"] for r in open_} == {"Do it", "Going"}
    assert done["id"] not in {r["id"] for r in open_}
    assert {r["status"] for r in open_} == {"open", "in_progress"}
    assert todo["id"] in {r["id"] for r in open_}


def test_tags_with_counts(store):
    write(store, tags=["tech/python", "home"])
    write(store, tags=["tech/rust"])
    out = ok(store, "tags")
    assert out["tags"][0] == ["tech", 2] and out["total"] == 4
    assert ok(store, "tags", prefix="TECH/")["tags"] == [
        ["tech/python", 1],
        ["tech/rust", 1],
    ]


def test_public_url_must_be_a_url():
    with pytest.raises(SystemExit, match="not a URL"):
        mcp_server.security(["scrap.example"])


def rpc(client, method, params=None, headers=None, id=1):
    body = {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers={**ACCEPT, **(headers or {})})


INIT = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "test", "version": "1"},
}


def test_mcp_over_http(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://scrap.example.ts.net:8446")
    app = create_app(tmp_path / "data")
    good = {"Host": "scrap.example.ts.net:8446"}
    with TestClient(app) as client:
        r = rpc(client, "initialize", INIT, good)
        assert r.status_code == 200, r.text
        assert r.json()["result"]["serverInfo"]["name"] == "scrap"
        tools = rpc(client, "tools/list", headers=good).json()["result"]["tools"]
        assert len(tools) == 6
        args = {"title": "Over HTTP", "body": "via /mcp", "origin": "test"}
        r = rpc(client, "tools/call", {"name": "write", "arguments": args}, good)
        written = r.json()["result"]["structuredContent"]
        assert written["url"].startswith("https://scrap.example.ts.net:8446/p/")
        r = rpc(
            client,
            "tools/call",
            {"name": "read", "arguments": {"page": written["id"]}},
            good,
        )
        text = json.loads(r.json()["result"]["content"][0]["text"])
        assert text["content"]["body_markdown"] == "via /mcp"
        # The page shows in the PWA's API as Claude's
        page = client.get(f"/api/pages/{written['id']}").json()
        assert page["captures"][0]["source"] == "mcp"
        assert (
            client.get("/api/search", params={"q": "is:claude"}).json()[0]["id"]
            == written["id"]
        )


@pytest.mark.parametrize(
    "headers, status",
    [
        ({"Host": "localhost:8790"}, 200),
        ({"Host": "127.0.0.1:8790"}, 200),
        ({"Host": "scrap.example.ts.net:8446"}, 200),
        ({"Host": "evil.example"}, 421),  # DNS rebinding
        ({"Host": "scrap.example.ts.net:8446", "Origin": "https://evil.example"}, 403),
        ({"Host": "localhost:8790", "Origin": "http://localhost:5173"}, 200),
        (
            {
                "Host": "scrap.example.ts.net:8446",
                "Origin": "https://scrap.example.ts.net:8446",
            },
            200,
        ),
    ],
)
def test_mcp_checks_host_and_origin(tmp_path, monkeypatch, headers, status):
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://scrap.example.ts.net:8446")
    with TestClient(create_app(tmp_path / "data")) as client:
        assert rpc(client, "initialize", INIT, headers).status_code == status


def test_mcp_without_a_public_url_is_loopback_only(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRAP_PUBLIC_URL", raising=False)
    with TestClient(create_app(tmp_path / "data")) as client:
        assert rpc(client, "initialize", INIT, {"Host": "a.ts.net"}).status_code == 421


def test_mcp_refuses_a_huge_request(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "MAX_REQUEST", 10_000)
    with TestClient(create_app(tmp_path / "data")) as client:
        args = {"title": "T", "body": "x" * 20_000, "origin": "o"}
        r = rpc(
            client,
            "tools/call",
            {"name": "write", "arguments": args},
            {"Host": "localhost"},
        )
        assert r.status_code == 413
