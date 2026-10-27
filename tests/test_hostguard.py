"""Host and Origin checks on the web app (#238): the review's forged-Host/Origin repro
is refused on /api and /share, and what the PWA and the CLI send still passes."""

import pytest
from fastapi.testclient import TestClient

from scrap.app import create_app
from scrap.hostguard import split
from scrap.store import new_ulid

PUBLIC = "https://scrap.example.ts.net:8446"
SHARE = {"title": "x", "text": "forged https://a.example"}


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_PUBLIC_URL", PUBLIC)
    with TestClient(create_app(tmp_path / "data")) as client:
        yield client


def pages(client):
    return client.get("/api/pages").json()


def test_the_reviews_forged_repro_is_refused(tmp_path):
    """Host and Origin both evil.example, as in the review: nothing is created."""
    forged = {"Host": "evil.example", "Origin": "http://evil.example"}
    with TestClient(create_app(tmp_path / "data")) as client:
        r = client.post("/share", data=SHARE, headers=forged, follow_redirects=False)
        assert r.status_code == 421
        body = {"id": new_ulid(), "text": "forged"}
        r = client.post("/api/captures", json=body, headers=forged)
        assert r.status_code == 421
        assert (
            client.get("/api/search", headers={"Host": "evil.example"}).status_code
            == 421
        )
        assert pages(client) == []


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "scrap.example.ts.net:9999",  # a port the URL did not name
        "scrap.example.ts.net.evil.example",
        "evil.example:8446",
        "scrap.example.ts.net@evil.example",
        "",
    ],
)
def test_a_host_not_listed_is_421_for_every_method(served, host):
    for method in ("GET", "HEAD", "OPTIONS", "POST", "DELETE"):
        r = served.request(method, "/api/pages", headers={"Host": host})
        assert r.status_code == 421, (method, host)
    assert served.get("/", headers={"Host": host}).status_code == 421


@pytest.mark.parametrize(
    "host",
    [
        "scrap.example.ts.net:8446",
        "SCRAP.Example.TS.net:8446",  # case
        "scrap.example.ts.net.:8446",  # trailing dot
        "localhost",
        "localhost:5173",
        "127.0.0.1:8000",
        "[::1]:8000",
        "192.168.1.10:8000",  # an address: nothing to rebind
        "100.64.0.7",
    ],
)
def test_listed_and_address_hosts_pass(served, host):
    assert served.get("/api/pages", headers={"Host": host}).status_code == 200


def test_a_public_url_without_a_port_accepts_any_port(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAP_PUBLIC_URL", "https://scrap.example.ts.net")
    with TestClient(create_app(tmp_path / "data")) as client:
        for host in ("scrap.example.ts.net", "scrap.example.ts.net:443"):
            assert client.get("/api/pages", headers={"Host": host}).status_code == 200


def test_x_forwarded_host_does_not_make_a_host_allowed(served):
    spoof = {"Host": "evil.example", "X-Forwarded-Host": "scrap.example.ts.net:8446"}
    assert served.get("/api/pages", headers=spoof).status_code == 421


def test_two_host_headers_are_refused(served):
    r = served.get(
        "/api/pages", headers=[("Host", "localhost"), ("Host", "evil.example")]
    )
    assert r.status_code == 421


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "null",  # a sandboxed iframe's form, or a cross-origin redirect
        "",
        "https://scrap.example.ts.net:9999",
        "http://scrap.example.ts.net:8446",  # not its scheme
        "https://scrap.example.ts.net:8446.evil.example",
        "https://scrap.example.ts.net:8446/x",
        "https://localhost",  # loopback is http only
        "file://",
        "http://127.0.0.1.evil.example",
    ],
)
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_writing_request_from_another_origin_is_403(served, method, origin):
    host = {"Host": "scrap.example.ts.net:8446", "Origin": origin}
    r = served.request(method, "/api/pages/nothing", headers=host)
    assert r.status_code == 403, r.text
    r = served.post("/share", data=SHARE, headers=host, follow_redirects=False)
    assert r.status_code == 403
    r = served.post("/api/captures", json={"id": new_ulid(), "text": "x"}, headers=host)
    assert r.status_code == 403
    assert pages(served) == []


def test_a_form_post_with_a_forged_origin_creates_nothing(served):
    forged = {"Host": "scrap.example.ts.net:8446", "Origin": "https://evil.example"}
    r = served.post("/share", data=SHARE, headers=forged, follow_redirects=False)
    assert r.status_code == 403
    assert pages(served) == []


def test_the_pwa_posts_from_its_own_origin(served):
    """What the PWA sends over Tailscale Serve: its Host and Origin."""
    own = {"Host": "scrap.example.ts.net:8446", "Origin": PUBLIC}
    body = {"id": new_ulid(), "text": "from the app"}
    assert served.post("/api/captures", json=body, headers=own).status_code == 201
    r = served.post("/share", data=SHARE, headers=own, follow_redirects=False)
    assert r.status_code == 303  # the share target's form POST
    [first] = [p for p in pages(served) if p["title"] != "from the app"] or [None]
    assert first is not None
    key = first["id"]
    assert served.patch(
        f"/api/pages/{key}", json={"status": "done"}, headers=own
    ).status_code
    assert served.delete(f"/api/pages/{key}", headers=own).status_code == 204


@pytest.mark.parametrize(
    "host, origin",
    [
        ("localhost:8000", "http://localhost:8000"),
        ("localhost:8000", "http://localhost:5173"),  # the Vite dev server
        ("192.168.1.10:8000", "http://192.168.1.10:8000"),  # no SCRAP_PUBLIC_URL set
        ("[::1]:8000", "http://[::1]:8000"),
    ],
)
def test_a_fresh_install_serves_its_own_origin(tmp_path, monkeypatch, host, origin):
    monkeypatch.delenv("SCRAP_PUBLIC_URL", raising=False)
    with TestClient(create_app(tmp_path / "data")) as client:
        h = {"Host": host, "Origin": origin}
        r = client.post(
            "/api/captures", json={"id": new_ulid(), "text": "hi"}, headers=h
        )
        assert r.status_code == 201, r.text


def test_an_address_page_cannot_write_to_another_address(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRAP_PUBLIC_URL", raising=False)
    with TestClient(create_app(tmp_path / "data")) as client:
        h = {"Host": "192.168.1.10:8000", "Origin": "http://6.6.6.6"}
        assert (
            client.post(
                "/api/captures", json={"id": new_ulid(), "text": "x"}, headers=h
            ).status_code
            == 403
        )


def test_no_origin_passes_as_the_cli_and_scripts_send_it(served):
    h = {"Host": "scrap.example.ts.net:8446"}  # curl, hooks: no Origin
    assert (
        served.post(
            "/api/captures", json={"id": new_ulid(), "text": "hi"}, headers=h
        ).status_code
        == 201
    )
    assert (
        served.post("/share", data=SHARE, headers=h, follow_redirects=False).status_code
        == 303
    )
    assert served.get("/api/pages", headers=h).status_code == 200


def test_a_read_from_another_origin_is_left_to_the_browser(served):
    """No CORS headers, so a page cannot read the reply; only the Host is checked."""
    h = {"Host": "scrap.example.ts.net:8446", "Origin": "https://evil.example"}
    assert served.get("/api/pages", headers=h).status_code == 200


def test_healthz_answers_any_host(served):
    assert (
        served.get("/healthz", headers={"Host": "scrap.svc.cluster.local"}).status_code
        == 200
    )


def test_mcp_keeps_its_own_check(served):
    r = served.post("/mcp", json={}, headers={"Host": "evil.example"})
    assert r.status_code == 421


@pytest.mark.parametrize(
    "value, parsed",
    [
        ("Example.COM.:80", ("example.com", "80")),
        ("[::1]:8000", ("[::1]", "8000")),
        ("[::1]", ("[::1]", "")),
        ("host", ("host", "")),
        ("host:x", None),
        ("[::1", None),
        ("a/b", None),
        ("", None),
    ],
)
def test_split(value, parsed):
    assert split(value) == parsed
