"""The MCP server (#37): its tools, called in process, and /mcp over ASGI."""

import asyncio
import json
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client

from scrap import mcp_server
from scrap.app import create_app
from scrap.ingest import put_derived
from scrap.mcp_page import page_key
from scrap.mcp_tools import writing
from scrap.store import Store, new_ulid, now

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


TO_DO = "kind:todo -is:done -is:cancelled -is:snoozed"  # what todos used to list


def write(store, **args: Any) -> dict[str, Any]:
    return ok(store, "write", **{"title": "T", "body": "B", "origin": "o", **args})


def test_tools_are_listed(store):
    async def main():
        async with Client(mcp_server.server(store)) as client:
            return [t.name for t in (await client.list_tools()).tools]

    tools = anyio.run(main)
    assert sorted(tools) == [
        "drawing", "edit_meta", "edit_page", "read", "rename_tag", "revert",
        "revisions", "search", "tags", "topics", "trash", "undelete", "write",
    ]  # fmt: skip


def test_write_makes_a_claude_page_with_provenance(store, monkeypatch):
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://scrap.example.ts.net:8446")
    out = write(
        store,
        title="  Findings  on\tMCP ",
        body="# Hi\n\nSome *findings*.",
        tags=["#Tech", "tech", "Claude Code"],
        kind="todo",
        status="in_progress",
        origin="myproject 2026-10-20",
    )
    assert out["created"] is True
    assert out["url"] == f"https://scrap.example.ts.net:8446/p/{out['slug']}"
    page = store.page(out["id"])
    assert page["title"] == "Findings on MCP"
    assert page["kind"] == "todo" and page["kind_fixed"] == 1
    assert page["fields"] == {"status": "in_progress", "origin": "myproject 2026-10-20"}
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
        store, "write", title="T", body="", origin="", kind="bogus"
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


def test_a_key_reused_for_another_page_still_writes(store):
    a = write(store, key="k1", title="A", body="a")
    b = write(store, title="B", body="b")
    out = write(store, append_to=b["slug"], body="more", key="k1")
    assert out["id"] == b["id"] and out["created"] is True
    assert store.page(b["id"])["body"] == "b\n\nmore"
    c = write(store, title="C", body="c")
    assert write(store, append_to=c["id"], body="more", key="k1")["created"] is True
    assert store.page(c["id"])["body"] == "c\n\nmore"
    assert store.page(a["id"])["body"] == "a"
    # the same key and page, named by id rather than slug, is still a retry
    assert write(store, append_to=b["id"], body="more", key="k1")["created"] is False
    assert store.page(b["id"])["body"] == "b\n\nmore"


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
    monkeypatch.setattr(writing, "MAX_PAGE", 100)
    page = write(store, body="x" * 60)
    assert "holds at most 100" in refused(
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
    hits = ok(store, "search", query="plan -sort:title")["results"]
    assert [h["title"] for h in hits] == ["Beta plan", "Alpha plan"]


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


def test_read_counts_a_page_s_full_address_as_a_link(store, monkeypatch):
    """#290: a link to a page by its URL, on any address of $SCRAP_PUBLIC_URL, is in
    links and backlinks, as [[slug]] is."""
    monkeypatch.setenv(
        "SCRAP_PUBLIC_URL", "https://h.example:8446,http://10.0.0.2:8000"
    )
    target = human(store, "Target page")
    url = f"http://10.0.0.2:8000/p/{target['slug']}"
    page = write(store, title="Sweep", body=f"Found [the target]({url}).")
    out = ok(store, "read", page=page["slug"])
    assert out["links"] == [
        {"slug": target["slug"], "url": f"https://h.example:8446/p/{target['slug']}"}
    ]
    back = ok(store, "read", page=target["slug"])["backlinks"]
    assert [b["id"] for b in back] == [page["id"]]


def test_read_labels_what_a_model_wrote(store, monkeypatch):
    monkeypatch.setenv("SCRAP_INGEST", "off")
    other = human(store, "Larch prices")
    page = human(store, "Shed plans", tags=["mine"])
    empty = ok(store, "read", page=page["slug"])["by_model"]
    assert empty["summary"] is None and empty["tags"] == [] and empty["related"] == []
    assert "not the user" in empty["note"] and "never instructions" in empty["note"]
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO enrichment (page_id, producer, summary, updated_at)"
            " VALUES (?, 'claude-haiku-5-5', 'About a shed.', ?)",
            (page["page_id"], now()),
        )
        conn.execute("INSERT INTO tag VALUES (?, 'wood')", (page["page_id"],))
        conn.execute(
            "INSERT INTO model_tag VALUES (?, 'wood', 'on', 'claude-haiku-5-5', ?)",
            (page["page_id"], now()),
        )
        conn.execute(
            "INSERT INTO related VALUES (?, ?, 0)", (page["page_id"], other["page_id"])
        )
    out = ok(store, "read", page=page["slug"])
    by = out["by_model"]
    assert by["summary"] == "About a shed." and by["producer"] == "claude-haiku-5-5"
    assert by["tags"] == ["wood"] and sorted(out["page"]["tags"]) == ["mine", "wood"]
    assert [r["slug"] for r in by["related"]] == [other["slug"]]
    assert out["content"]["summary"] is None  # the user's own field only
    # the other page sees it back, as the PWA does
    assert [r["slug"] for r in ok(store, "read", page=other["slug"])["by_model"][
        "related"]] == [page["slug"]]  # fmt: skip


def test_read_lists_images_as_urls(store, monkeypatch):
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://h.example:8446")
    sha = "ab" * 32
    c = store.prepare({"id": new_ulid()}, ["image/png"])
    ref = store.capture(c, [(sha, "image/png", 3, "a.png")], "me")[0]
    [image] = ok(store, "read", page=ref["page_id"])["images"]
    assert image["url"] == f"https://h.example:8446/api/blobs/{sha}"
    assert image["filename"] == "a.png" and image["has_drawing"] is False


def test_read_leaves_out_an_image_whose_embed_was_deleted(store):
    """#303: the capture keeps the file, but the page no longer shows it."""
    sha = "ef" * 32
    c = store.prepare({"id": new_ulid()}, ["image/png"])
    ref = store.capture(c, [(sha, "image/png", 3, "a.png")], "me")[0]
    page = store.page(ref["page_id"])
    assert [i["sha256"] for i in ok(store, "read", page=ref["page_id"])["images"]] == [
        sha
    ]
    store.update_page(ref["page_id"], page["rev"], None, "No picture", "me")
    assert ok(store, "read", page=ref["page_id"])["images"] == []
    assert ok(store, "search", query="has:image")["results"] == []
    [row] = ok(store, "search", query="picture")["results"]  # the count too
    assert row["id"] == ref["page_id"] and row["image_count"] == 0
    assert "image_url" not in row


def test_read_of_a_missing_or_trashed_page(store):
    page = write(store)
    assert "no such page" in refused(store, "read", page="missing")
    store.delete_page(page["id"])
    assert ok(store, "read", page=page["id"])["page"]["trashed"] is True  # read only


def test_empty_search_lists_recent_and_todos_by_query(store):
    write(store, title="Note one")
    todo = write(store, title="Do it", kind="todo")
    done = write(store, title="Done it", kind="todo", status="done")
    write(store, title="Going", kind="todo", status="in_progress")
    titles = [r["title"] for r in ok(store, "search")["results"]]
    assert titles == ["Going", "Done it", "Do it", "Note one"]
    assert len(ok(store, "search", limit=1)["results"]) == 1
    assert [r["title"] for r in ok(store, "search", query="kind:todo")["results"]] == [
        "Going",
        "Done it",
        "Do it",
    ]
    open_ = ok(store, "search", query=TO_DO)["results"]
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
        assert len(tools) == 13
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


def photo_page(store, sha, description=None, image_kind=None, mime="image/jpeg"):
    """A photo page, as the PWA makes one, with what Claude made of it (if given)."""
    c = store.prepare({"id": new_ulid()}, [mime])
    ref = store.capture(c, [(sha, mime, 3, "p.jpg")], "me")[0]
    if description is not None:
        with store.connect() as conn:
            put_derived(
                conn, c["id"], sha, "description", "model", now(),
                text=description, data={"kind": image_kind},
            )  # fmt: skip
    return ref


def test_rows_say_what_images_a_page_has(store, monkeypatch):
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://h.example:8446")
    sha = "cd" * 32
    pic = photo_page(store, sha, "A green praying mantis on a tile.", "photo")
    write(store, title="Plain note")
    pending = photo_page(store, "ef" * 32)  # not read by Claude yet
    rows = {r["id"]: r for r in ok(store, "search")["results"]}
    got = rows[pic["page_id"]]
    assert got["image_count"] == 1
    assert got["image_kind"] == "photo"
    assert got["image_description"] == "A green praying mantis on a tile."
    assert got["image_url"] == f"https://h.example:8446/api/blobs/{sha}"
    assert (
        got["thumbnail_url"]
        == f"https://h.example:8446/api/blobs/{sha}/preview?size=480"
    )
    assert rows[pending["page_id"]]["image_count"] == 1
    assert rows[pending["page_id"]]["image_kind"] is None
    plain = next(r for r in rows.values() if r["title"] == "Plain note")
    assert plain["image_count"] == 0 and "image_kind" not in plain
    # search rows carry the same fields
    [hit] = ok(store, "search", query="mantis")["results"]
    assert hit["id"] == pic["page_id"] and hit["image_kind"] == "photo"
    assert "mantis" in hit["snippet"]  # the description is searchable text


def test_image_count_counts_every_image_and_the_first_leads(store):
    first, second = "11" * 32, "22" * 32
    c = store.prepare({"id": new_ulid()}, ["image/png", "image/png", "text/plain"])
    ref = store.capture(
        c,
        [(first, "image/png", 3, "a.png"), (second, "image/png", 3, "b.png"),
         ("33" * 32, "text/plain", 3, "c.txt")],
        "me",
    )[0]  # fmt: skip
    with store.connect() as conn:
        put_derived(conn, c["id"], second, "description", "m", now(), text="second",
                    data={"kind": "diagram"})  # fmt: skip
    [row] = ok(store, "search")["results"]
    assert row["id"] == ref["page_id"] and row["image_count"] == 2
    assert row["image_url"].endswith(first) and row["image_description"] is None


def test_image_filters(store):
    mantis = photo_page(store, "aa" * 32, "A mantis.", "photo")
    board = photo_page(store, "bb" * 32, "A plan on a whiteboard.", "whiteboard")
    note = write(store, title="No picture")

    def ids(query):
        return {r["id"] for r in ok(store, "search", query=query)["results"]}

    assert ids("has:image") == {mantis["page_id"], board["page_id"]}
    assert ids("-has:image kind:note") == {note["id"]}
    assert ids("image:photo") == {mantis["page_id"]}
    assert ids("image:Whiteboard") == {board["page_id"]}
    assert ids("-image:photo has:image") == {board["page_id"]}
    assert ids("has:nonsense") == set()
    assert ids("has:drawing") == set()
    with store.connect() as conn:
        cid = store.page(board["page_id"])["captures"][0]["id"]
        put_derived(
            conn, cid, "bb" * 32, "excalidraw", "m", now(), data={"elements": []}
        )
    assert ids("has:drawing") == {board["page_id"]}
    assert ids("plan has:image") == {board["page_id"]}


def test_read_gives_image_thumbnails(store, monkeypatch):
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://h.example:8446")
    ref = photo_page(store, "dd" * 32, "A cat.", "photo")
    [image] = ok(store, "read", page=ref["page_id"])["images"]
    assert image["thumbnail_url"].endswith("/preview?size=480")
    assert image["description"] == "A cat." and image["image_kind"] == "photo"


def test_todos_have_due_dates_and_priorities(store):
    a = write(store, title="A", kind="todo", due="2026-11-03", priority="low")
    b = write(store, title="B", kind="todo", due="2026-11-01")
    c = write(store, title="C", kind="todo", priority="high")
    write(store, title="N")  # a note: none
    rows = ok(store, "search", query=TO_DO)["results"]
    assert {r["title"]: (r["due"], r["priority"]) for r in rows} == {
        "A": ("2026-11-03", "low"), "B": ("2026-11-01", None), "C": (None, "high"),
    }  # fmt: skip
    by_due = ok(store, "search", query=f"{TO_DO} sort:due")["results"]
    assert [r["id"] for r in by_due] == [b["id"], a["id"], c["id"]]
    by_rank = ok(
        store,
        "search",
        query=f"{TO_DO} sort:priority",
    )["results"]
    assert [r["id"] for r in by_rank] == [c["id"], a["id"], b["id"]]
    found = ok(store, "search", query="due:<=2026-11-02")["results"]
    assert [r["id"] for r in found] == [b["id"]]
    assert ok(store, "search", query="priority:high")["results"][0]["id"] == c["id"]
    assert ok(store, "search", limit=1)["results"][0]["due"] is None  # N
    page = ok(store, "read", page=a["id"])["page"]
    assert (page["due"], page["priority"]) == ("2026-11-03", "low")


def test_write_checks_due_and_priority(store):
    for args, error in [
        ({"kind": "note", "due": "2026-11-01"}, "for todos"),
        ({"kind": "todo", "due": "Friday"}, "YYYY-MM-DD"),
        ({"kind": "todo", "priority": "urgent"}, "priority must be"),
    ]:
        assert error in refused(store, "write", title="T", body="", origin="o", **args)
    assert store.recent(5) == []


def test_append_sets_due_and_priority_on_a_claude_todo_only(store):
    todo = write(store, title="Plan", kind="todo", due="2026-11-01")
    out = write(store, append_to=todo["id"], body="", priority="high", due="none")
    assert out["created"] is True
    p = store.page(todo["id"])
    assert (p["due"], p["priority"], p["rev"]) == (None, "high", 1)  # no revision
    note = write(store, title="Log", body="first")
    assert "for todos" in refused(
        store,
        "write",
        title="",
        body="x",
        origin="",
        append_to=note["id"],
        due="2026-11-01",
    )
    assert store.page(note["id"])["body"] == "first"  # nothing appended either
    human_todo = human(store, "mine", kind="todo")
    assert "only a page written over MCP" in refused(
        store, "write", title="", body="", origin="", append_to=human_todo["page_id"],
        priority="low",
    )  # fmt: skip
    assert store.page(human_todo["page_id"])["priority"] is None


SECRET = "s3cret-token-value"
LOCAL = {"Host": "localhost"}


def authed(tmp_path, monkeypatch, token: str | None = SECRET, **env):
    monkeypatch.delenv("SCRAP_MCP_TOKEN_FILE", raising=False)
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://scrap.example.ts.net:8446")
    if token is not None:
        monkeypatch.setenv("SCRAP_MCP_TOKEN", token)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return TestClient(create_app(tmp_path / "data"))


def bearer(token):
    return {**LOCAL, "Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    "headers, status",
    [
        (LOCAL, 401),
        ({**LOCAL, "Authorization": "Bearer wrong"}, 401),
        ({**LOCAL, "Authorization": "Bearer"}, 401),
        ({**LOCAL, "Authorization": f"Basic {SECRET}"}, 401),
        ({**LOCAL, "Authorization": SECRET}, 401),
        (bearer(SECRET), 200),
        ({**LOCAL, "Authorization": f"bearer {SECRET}"}, 200),
    ],
)
def test_mcp_token_is_required(tmp_path, monkeypatch, headers, status):
    with authed(tmp_path, monkeypatch) as client:
        r = rpc(client, "initialize", INIT, headers)
        assert r.status_code == status
        if status == 401:
            assert r.headers["WWW-Authenticate"] == "Bearer"
            assert SECRET not in r.text


def test_mcp_token_is_checked_before_host_and_origin(tmp_path, monkeypatch):
    with authed(tmp_path, monkeypatch) as client:
        # a bad Host or Origin without the token is a 401, not a 421 or 403
        assert (
            rpc(client, "initialize", INIT, {"Host": "evil.example"}).status_code == 401
        )
        bad_origin = {"Origin": "https://evil.example"}
        assert (
            rpc(client, "initialize", INIT, {**LOCAL, **bad_origin}).status_code == 401
        )
        # with it, Host and Origin still apply
        good = {"Authorization": f"Bearer {SECRET}"}
        r = rpc(client, "initialize", INIT, {"Host": "evil.example", **good})
        assert r.status_code == 421
        r = rpc(client, "initialize", INIT, {**LOCAL, **good, **bad_origin})
        assert r.status_code == 403


def test_mcp_token_dispatches_no_tool_without_it(tmp_path, monkeypatch):
    with authed(tmp_path, monkeypatch) as client:
        args = {"title": "T", "body": "B", "origin": "o"}
        r = rpc(client, "tools/call", {"name": "write", "arguments": args}, LOCAL)
        assert r.status_code == 401
        assert client.get("/api/search", params={"q": "is:claude"}).json() == []
        r = rpc(
            client, "tools/call", {"name": "write", "arguments": args}, bearer(SECRET)
        )
        assert r.status_code == 200
        assert len(client.get("/api/search", params={"q": "is:claude"}).json()) == 1


def test_mcp_token_leaves_the_rest_open(tmp_path, monkeypatch):
    with authed(tmp_path, monkeypatch) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/search", params={"q": "x"}).status_code == 200
        assert client.get("/").status_code in (200, 503)  # the PWA, built or not


def test_mcp_without_a_token_is_unchanged(tmp_path, monkeypatch):
    with TestClient(create_app(tmp_path / "data")) as client:
        assert rpc(client, "initialize", INIT, LOCAL).status_code == 200
        r = rpc(client, "initialize", INIT, {**LOCAL, "Authorization": "Bearer x"})
        assert r.status_code == 200


def test_mcp_takes_several_tokens(tmp_path, monkeypatch):
    with authed(tmp_path, monkeypatch, token=" old , new ,") as client:
        for token, status in (("old", 200), ("new", 200), ("older", 401)):
            assert rpc(client, "initialize", INIT, bearer(token)).status_code == status


def test_mcp_tokens_from_a_file(tmp_path, monkeypatch):
    file = tmp_path / "tokens"
    file.write_text("# laptop\nlaptop-token\n\n  phone-token  \n")
    with authed(
        tmp_path, monkeypatch, token="env-token", SCRAP_MCP_TOKEN_FILE=str(file)
    ) as client:
        for token, status in (
            ("laptop-token", 200),
            ("phone-token", 200),
            ("env-token", 200),
            ("# laptop", 401),
            ("", 401),
        ):
            assert rpc(client, "initialize", INIT, bearer(token)).status_code == status


@pytest.mark.parametrize("env", [{"SCRAP_MCP_TOKEN": ""}, {"SCRAP_MCP_TOKEN": " , "}])
def test_mcp_empty_token_stops_scrap(tmp_path, monkeypatch, env):
    monkeypatch.delenv("SCRAP_MCP_TOKEN_FILE", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(SystemExit, match="holds no token"):
        create_app(tmp_path / "data")


@pytest.mark.parametrize("content", [None, "", "# only a comment\n"])
def test_mcp_bad_token_file_stops_scrap(tmp_path, monkeypatch, content):
    file = tmp_path / "tokens"
    if content is not None:
        file.write_text(content)
    monkeypatch.delenv("SCRAP_MCP_TOKEN", raising=False)
    monkeypatch.setenv("SCRAP_MCP_TOKEN_FILE", str(file))
    with pytest.raises(SystemExit, match="SCRAP_MCP_TOKEN"):
        create_app(tmp_path / "data")


def test_mcp_token_compare_is_constant_time(tmp_path, monkeypatch):
    seen = []
    real = mcp_server.hmac.compare_digest
    monkeypatch.setattr(
        mcp_server.hmac,
        "compare_digest",
        lambda a, b: seen.append((a, b)) or real(a, b),
    )
    with authed(tmp_path, monkeypatch, token="one,two") as client:
        assert rpc(client, "initialize", INIT, bearer("wrong")).status_code == 401
    assert seen == [(b"wrong", b"one"), (b"wrong", b"two")]  # none skipped


def test_mcp_token_is_never_logged(tmp_path, monkeypatch, caplog):
    caplog.set_level("DEBUG")
    with authed(tmp_path, monkeypatch) as client:
        rpc(client, "initialize", INIT, bearer("a-wrong-one"))
        rpc(client, "initialize", INIT, bearer(SECRET))
    assert SECRET not in caplog.text
    assert "a-wrong-one" not in caplog.text


def test_mcp_bearer_guards_slash_head_options(tmp_path, monkeypatch):
    with authed(tmp_path, monkeypatch) as client:
        for method, path in (
            ("POST", "/mcp/"),
            ("HEAD", "/mcp"),
            ("OPTIONS", "/mcp"),
        ):
            r = client.request(method, path, headers=LOCAL)
            assert r.status_code == 401, (method, path)
            assert r.headers["WWW-Authenticate"] == "Bearer"


def test_mcp_token_file_with_bom(tmp_path, monkeypatch):
    file = tmp_path / "tokens"
    file.write_bytes(b"\xef\xbb\xbffirst-token\nsecond-token\n")
    with authed(
        tmp_path, monkeypatch, token=None, SCRAP_MCP_TOKEN_FILE=str(file)
    ) as client:
        for token in ("first-token", "second-token"):
            assert rpc(client, "initialize", INIT, bearer(token)).status_code == 200


def asgi_status(headers, path="/mcp", root_path=""):
    sent = []

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "root_path": root_path,
        "headers": headers,
    }
    asyncio.run(mcp_server.BearerAuth(inner, [SECRET])(scope, receive, send))
    return sent[0]["status"]


def test_mcp_bearer_only_the_first_authorization_header_counts():
    good = (b"authorization", f"Bearer {SECRET}".encode())
    bad = (b"authorization", b"Bearer wrong")
    assert asgi_status([good, bad]) == 200
    assert asgi_status([bad, good]) == 401


def test_mcp_bearer_with_a_root_path():
    assert asgi_status([], "/prefix/mcp", "/prefix") == 401
    assert asgi_status([], "/prefix/mcp/x", "/prefix") == 401
    assert asgi_status([], "/prefix/healthz", "/prefix") == 200
    assert asgi_status([], "/mcp") == 401


def test_a_page_key_starting_with_revision_is_still_no_such_page(store):
    """The wording follows the exception type, not the text of the key (#154)."""
    out = refused(store, "read", page="revision 9")
    assert "no such page: revision 9" in out
    assert "no such revision" not in out


def with_drawing(store, ref, sha, elements, producer="model", **extra):
    """Give a photo (on the page `ref`) a current drawing."""
    cid = store.page(ref["page_id"])["captures"][0]["id"]
    data = {"format": "skeleton", "width": 800, "height": 600,
            "elements": elements, **extra}  # fmt: skip
    with store.connect() as conn:
        put_derived(conn, cid, sha, "excalidraw", producer, now(), data=data)


BOX = {"type": "rectangle", "x": 1, "y": 2, "width": 3, "height": 4}


def test_read_shows_drawing_metadata(store):
    sha = "ab" * 32
    ref = photo_page(store, sha)
    [image] = ok(store, "read", page=ref["page_id"])["images"]
    assert image["drawing"] is None and image["has_drawing"] is False
    with_drawing(store, ref, sha, [BOX, BOX])
    [image] = ok(store, "read", page=ref["page_id"])["images"]
    assert image["has_drawing"] is True
    assert image["drawing"] == {
        "version": 1, "producer": "model", "width": 800, "height": 600,
        "element_count": 2,
    }  # fmt: skip


def test_drawing_by_sha_prefix_or_alone(store):
    sha = "ab" * 32
    ref = photo_page(store, sha)
    with_drawing(store, ref, sha, [BOX])
    for args in ({"image": sha}, {"image": sha[:6]}, {}):
        out = ok(store, "drawing", page=ref["page_id"], **args)
        assert out == {
            "version": 1,
            "producer": "model",
            "format": "skeleton",
            "width": 800,
            "height": 600,
            "elements": [BOX],
            "truncated": False,
        }


def test_drawing_says_a_human_scene_is_a_scene(store):
    sha = "ab" * 32
    ref = photo_page(store, sha)
    with_drawing(store, ref, sha, [BOX], producer="human", format="scene")
    out = ok(store, "drawing", page=ref["page_id"])
    assert out["format"] == "scene" and out["producer"] == "human"


def test_drawing_needs_an_image_when_there_are_several(store):
    a, b = "ab" * 32, "ac" * 32
    c = store.prepare({"id": new_ulid()}, ["image/png", "image/png"])
    ref = store.capture(
        c, [(a, "image/png", 3, "a.png"), (b, "image/png", 3, "b.png")], "me"
    )[0]
    with_drawing(store, ref, a, [BOX])
    with_drawing(store, ref, b, [BOX])
    error = refused(store, "drawing", page=ref["page_id"])
    assert a in error and b in error
    assert a in refused(store, "drawing", page=ref["page_id"], image="a")  # ambiguous
    assert ok(store, "drawing", page=ref["page_id"], image="ab")["elements"] == [BOX]


def test_drawing_errors(store):
    sha = "ab" * 32
    ref = photo_page(store, sha)
    assert "no image with a drawing" in refused(store, "drawing", page=ref["page_id"])
    with_drawing(store, ref, sha, [BOX])
    assert "no drawing for image" in refused(
        store, "drawing", page=ref["page_id"], image="ff"
    )
    other = photo_page(store, "cd" * 32)  # a page whose photo has no drawing
    assert "no drawing for image" in refused(
        store, "drawing", page=other["page_id"], image=sha
    )
    assert "no such page" in refused(store, "drawing", page="nope")


def test_drawing_is_cut_at_the_size_cap(store):
    sha = "ab" * 32
    ref = photo_page(store, sha)
    big = {"type": "text", "x": 0, "y": 0, "text": "x" * 50_000}
    with_drawing(store, ref, sha, [big] * 10)
    out = ok(store, "drawing", page=ref["page_id"])
    assert out["truncated"] is True
    assert 0 < len(out["elements"]) < 10
    assert len(json.dumps(out["elements"])) <= mcp_server.MAX_DRAWING


def test_read_lists_only_images_under_images_and_other_files_apart(store):
    img, doc = "44" * 32, "55" * 32
    c = store.prepare({"id": new_ulid()}, ["image/png", "application/pdf"])
    ref = store.capture(
        c, [(img, "image/png", 3, "a.png"), (doc, "application/pdf", 3, "d.pdf")], "me"
    )[0]
    out = ok(store, "read", page=ref["page_id"])
    assert [i["sha256"] for i in out["images"]] == [img]
    assert out["images"][0]["thumbnail_url"] is not None
    [other] = out["files"]
    assert other["sha256"] == doc and other["filename"] == "d.pdf"
    assert other["thumbnail_url"] is None


def test_image_count_counts_a_repeated_image_once(store):
    sha = "66" * 32
    c = store.prepare({"id": new_ulid()}, ["image/png", "image/png"])
    store.capture(
        c, [(sha, "image/png", 3, "a.png"), (sha, "image/png", 3, "again.png")], "me"
    )
    [row] = ok(store, "search")["results"]
    assert row["image_count"] == 1 and row["image_url"].endswith(sha)


def trashed(store, **args):
    """A page written over MCP, then deleted (in the PWA, say)."""
    page = write(store, **args)
    store.delete_page(page["id"])
    return page


def test_revisions_without_page_or_batch_is_the_recent_changes_feed(store):
    old = human(store, "an old page")
    gone = human(store, "going page")
    new = write(store, title="Fresh", body="b")
    ok(store, "edit_meta", pages=[old["slug"]], add_tags=["x"])
    ok(store, "edit_page", page=new["slug"], old="b", new="c")
    ok(store, "edit_meta", pages=[gone["slug"]], add_tags=["z"])
    store.delete_page(gone["slug"])
    out = ok(store, "revisions", limit=50)
    assert [m["slug"] for m in out["meta"]] == [old["slug"]]  # not gone's
    meta = out["meta"][0]
    assert (meta["author"], meta["source"]) == ("claude", "mcp")
    assert meta["batch_id"] is None and meta["tags_added"] == ["x"]
    slugs = [t["slug"] for t in out["text"]]
    assert gone["slug"] not in slugs  # the trash is absent from the feed
    assert set(slugs) == {old["slug"], new["slug"]}
    assert {t["author"] for t in out["text"]} >= {"claude"}
    assert all(t["url"].endswith(f"/p/{t['slug']}") for t in out["text"])
    assert len(ok(store, "revisions", limit=1)["text"]) == 1
    assert "text_rev needs a page" in refused(store, "revisions", text_rev=1)


def test_feed_is_newest_first_and_empty_on_a_quiet_store(store):
    assert ok(store, "revisions")["meta"] == []
    a, b = human(store, "first"), human(store, "second")
    ok(store, "edit_meta", pages=[a["slug"]], add_tags=["x"])
    ok(store, "edit_meta", pages=[b["slug"]], add_tags=["y"])
    assert [m["slug"] for m in ok(store, "revisions")["meta"]] == [b["slug"], a["slug"]]


def test_trash_lists_deleted_pages_newest_first(store):
    assert ok(store, "trash")["results"] == []
    a, b = write(store, title="Alpha"), write(store, title="Beta")
    keep = write(store, title="Kept")
    store.delete_page(a["id"])
    store.delete_page(b["id"])
    results = ok(store, "trash")["results"]
    assert [r["title"] for r in results] == ["Beta", "Alpha"]
    first = results[0]
    assert first["id"] == b["id"] and first["slug"] == b["slug"]
    assert first["kind"] == "note" and first["deleted_at"]
    assert first["url"].endswith(f"/p/{b['slug']}")
    assert len(ok(store, "trash", limit=1)["results"]) == 1
    assert keep["id"] not in {r["id"] for r in results}


def test_read_and_revisions_of_a_trashed_page_are_read_only(store):
    page = trashed(store, title="Doomed", body="last words", tags=["t"])
    out = ok(store, "read", page=page["slug"])
    assert out["page"]["trashed"] is True and out["page"]["deleted_at"]
    assert out["content"]["body_markdown"] == "last words"
    live = write(store, title="Live")
    assert ok(store, "read", page=live["slug"])["page"]["trashed"] is False
    assert ok(store, "read", page=live["slug"])["page"]["deleted_at"] is None
    revs = ok(store, "revisions", page=page["id"], text_rev=1)
    assert revs["trashed"] is True and revs["deleted_at"] == out["page"]["deleted_at"]
    assert revs["text_revision"]["body"] == "last words"
    assert ok(store, "revisions", page=live["slug"])["trashed"] is False


def test_every_other_tool_still_treats_the_trash_as_absent(store):
    page = trashed(store, title="Doomed zebra", body="b")
    key = page["slug"]
    assert ok(store, "search", query="zebra")["results"] == []
    assert ok(store, "search")["results"] == []
    assert ok(store, "search", query="kind:todo")["results"] == []
    assert ok(store, "tags")["total"] == 0
    for tool, args in (
        ("edit_meta", {"pages": [key], "add_tags": ["x"]}),
        ("edit_page", {"page": key, "old": "b", "new": "c"}),
        ("revert", {"page": key, "to_rev": 1, "dry_run": True}),
        ("write", {"title": "", "body": "more", "origin": "", "append_to": key}),
        ("drawing", {"page": key}),
    ):
        assert "no such page" in refused(store, tool, **args), tool
    assert ok(store, "revisions")["text"] == []


def test_undelete_brings_a_page_back(store):
    page = trashed(store, title="Doomed", body="words", tags=["t"])
    dry = ok(store, "undelete", page=page["slug"], dry_run=True)
    assert dry["dry_run"] is True and dry["restored"] is False
    assert dry["id"] == page["id"] and dry["url"].endswith(f"/p/{page['slug']}")
    assert ok(store, "read", page=page["id"])["page"]["trashed"] is True
    out = ok(store, "undelete", page=page["slug"])
    assert out["restored"] is True and out["title"] == "Doomed"
    back = ok(store, "read", page=page["id"])
    assert back["page"]["trashed"] is False and back["page"]["tags"] == ["t"]
    assert back["content"]["body_markdown"] == "words"
    assert ok(store, "trash")["results"] == []
    assert [r["id"] for r in ok(store, "search")["results"]] == [page["id"]]


def test_undelete_of_a_page_not_in_the_trash(store):
    live = write(store)
    assert "not in the trash" not in refused(store, "undelete", page="missing")
    assert "no such page in the trash" in refused(store, "undelete", page=live["slug"])
    assert "no such page in the trash" in refused(store, "undelete", page="missing")


def test_undelete_follows_the_content_edit_switch(store, monkeypatch):
    page = trashed(store)

    async def listed():
        async with Client(mcp_server.server(store)) as client:
            return [t.name for t in (await client.list_tools()).tools]

    assert "undelete" in anyio.run(listed)
    monkeypatch.setenv("SCRAP_MCP_CONTENT_EDIT", "0")
    names = anyio.run(listed)
    assert "undelete" not in names and "trash" in names  # listing stays
    assert "undelete" in refused(store, "undelete", page=page["id"])
    assert ok(store, "trash")["results"][0]["id"] == page["id"]
    assert "nothing here brings one back" in (
        mcp_server.server(store).instructions or ""
    )
    monkeypatch.setenv("SCRAP_MCP_CONTENT_EDIT", "1")
    assert "undelete brings one page back" in (
        mcp_server.server(store).instructions or ""
    )


def test_instructions_describe_the_trash_and_what_revisions_omit(store):
    text = " ".join((mcp_server.server(store).instructions or "").split())
    assert "deletes go to a trash" in text.replace("the user's ", "")
    assert "enrichment" in text and "not in them" in text


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("https://scrap.example/p/milk-list", "milk-list"),
        ("http://localhost:8000/p/milk-list/", "milk-list"),
        ("  https://x/p/milk-list?a=1#h ", "milk-list"),
        ("https://x/p/caf%C3%A9", "café"),
        ("milk-list", "milk-list"),
        ("01M5PFFZ50HX558ZG4S84NP0T6", "01M5PFFZ50HX558ZG4S84NP0T6"),
        ("https://x/api/pages/milk", "https://x/api/pages/milk"),
        ("https://x/p/a/b", "https://x/p/a/b"),
        ("HTTPS://x/p/a", "a"),
        ("https://[bad/p/a", "https://[bad/p/a"),
        ("httpsy-notes", "httpsy-notes"),
    ],
)
def test_page_key(value, key):
    assert page_key(value) == key


def test_tools_take_a_page_url(store):
    slug = human(store)["slug"]
    url = f"https://elsewhere.example/p/{slug}"
    err, read = call(store, "read", page=url)
    assert not err
    assert read["page"]["slug"] == slug
    err, edited = call(
        store, "edit_page", page=url, old="eggs", new="flour", rev=read["page"]["rev"]
    )
    assert not err
    assert "flour" in call(store, "read", page=slug)[1]["content"]["body_markdown"]
    err, _ = call(store, "write", body="more", append_to=url)
    assert err  # a page the user made is not appended to, as with its slug


def test_every_page_tool_takes_a_page_url(store):
    page = write(store, title="Mine", body="one")
    url = f"https://elsewhere.example/p/{page['slug']}"
    assert write(store, body="two", append_to=url)["id"] == page["id"]
    assert not call(store, "revisions", page=url)[0]
    assert not call(store, "edit_meta", pages=[url], add_tags=["x"])[0]
    rev = call(store, "read", page=url)[1]["page"]["rev"]
    assert not call(store, "revert", page=url, to_rev=1, rev=rev)[0]
    assert call(store, "undelete", page=url)[0]  # not in the trash: refused, found
    assert call(store, "drawing", page=url)[0]  # no drawing: refused, found


def test_search_refuses_an_unknown_kind(store):
    write(store, title="A note")
    error = refused(store, "search", query="kind:notes")
    assert "unknown kind" in error and "todo" in error
    assert ok(store, "search", query="kind:read")["results"] == []


def test_revert_refuses_text_options_without_to_rev(store):
    for extra in ({"rev": 1}, {"restore_title": True}, {"allow_empty": True}):
        assert "go with page and to_rev" in refused(
            store, "revert", revision=1, **extra
        )
        assert "go with page and to_rev" in refused(store, "revert", batch="x", **extra)
