"""scrap-public/receiver.py, run on a free port over a temporary site folder, with
uploads built by scrap.publish.unit (as scrap's client builds them)."""

import errno
import importlib.util
import io
import json
import signal
import socket
import subprocess
import sys
import tarfile
import threading
import time
import tracemalloc
from collections.abc import Iterator
from http.client import HTTPConnection
from pathlib import Path
from types import ModuleType

import pytest

from scrap.publish.unit import UnitError, build_unit, digest

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "t" * 40


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "scrap_public_receiver", ROOT / "scrap-public" / "receiver.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


receiver = _load()


class Running:
    def __init__(self, site: Path, **limits) -> None:
        config = receiver.Config(site=site, token=TOKEN, host="127.0.0.1", port=0)
        for name, value in limits.items():
            setattr(config, name, value)
        self.server = receiver.Server(config)
        self.port = self.server.server_address[1]
        self.site = site
        self.thread = threading.Thread(
            target=self.server.serve_forever, args=(0.02,), daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        token: str | None = TOKEN,
    ) -> tuple[int, dict, dict]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        if token is not None:
            h.setdefault("Authorization", f"Bearer {token}")
        conn.request(method, path, body=body, headers=h)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        payload = json.loads(raw) if raw else {}
        return response.status, payload, dict(response.getheaders())

    def put(self, unit: str, files: dict[str, bytes], **kw) -> tuple[int, dict]:
        tar, dig = build_unit(files)
        return self.put_raw(unit, tar, dig, **kw)

    def put_raw(self, unit: str, tar: bytes, dig: str, **kw) -> tuple[int, dict]:
        headers = {"Content-Type": "application/x-tar", "Scrap-Digest": dig}
        status, payload, _ = self.request(
            "PUT", f"/v1/units/{unit}", tar, headers, **kw
        )
        return status, payload

    def raw(self, data: bytes, wait: float = 5) -> bytes:
        """Send raw bytes and return the response's head and body."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=wait) as s:
            s.sendall(data)
            got = b""
            try:
                while chunk := s.recv(65536):
                    got += chunk
                    if b"\r\n\r\n" in got:
                        head, _, rest = got.partition(b"\r\n\r\n")
                        length = 0
                        for line in head.split(b"\r\n"):
                            if line.lower().startswith(b"content-length:"):
                                length = int(line.split(b":")[1])
                        if len(rest) >= length:
                            break
            except TimeoutError:
                pass
            return got


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Running]:
    running = Running(tmp_path / "site")
    yield running
    running.stop()


def page(text: str = "hello") -> dict[str, bytes]:
    return {"index.html": f"<p>{text}</p>".encode()}


def status_of(response: bytes) -> int:
    return int(response.split(b" ", 2)[1])


def tar_of(*members: tuple[tarfile.TarInfo, bytes | None]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for info, content in members:
            if content is not None:
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
            else:
                tar.addfile(info)
    return buffer.getvalue()


def member(name: str, kind: bytes = tarfile.REGTYPE, **attrs) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    for key, value in attrs.items():
        setattr(info, key, value)
    return info


# -- auth and startup


def test_healthz_needs_no_token(server: Running) -> None:
    status, payload, _ = server.request("GET", "/healthz", token=None)
    assert (status, payload) == (200, {"ok": True})


@pytest.mark.parametrize(
    "auth",
    [None, "", "Bearer", f"Bearer {TOKEN}x", f"Basic {TOKEN}", f"Bearer {TOKEN[:-1]}"],
)
def test_every_other_route_needs_the_token(server: Running, auth: str | None) -> None:
    headers = {} if auth is None else {"Authorization": auth}
    for method, path in [
        ("GET", "/v1/manifest"),
        ("DELETE", "/v1/units/home"),
        ("GET", "/nowhere"),
    ]:
        status, payload, h = server.request(method, path, headers=headers, token=None)
        assert status == 401, (method, path)
        assert payload["error"] == "unauthorized"
        assert h["WWW-Authenticate"] == "Bearer"
        assert TOKEN not in json.dumps(payload)


def test_a_bad_token_is_never_logged(
    server: Running, capfd: pytest.CaptureFixture[str]
) -> None:
    server.request("GET", "/v1/manifest", token="s" * 40)
    server.request("GET", "/v1/manifest")
    err = capfd.readouterr().err
    assert "s" * 40 not in err and TOKEN not in err
    assert "/v1/manifest" in err


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"RECEIVER_TOKEN": "short"},
        {"RECEIVER_TOKEN": "a" * 20 + " " + "b" * 20},
        {"RECEIVER_TOKEN_FILE": "/nonexistent/token"},
    ],
)
def test_a_missing_or_weak_token_stops_the_start(env: dict[str, str]) -> None:
    with pytest.raises(SystemExit):
        receiver.config_from_env(env)


def test_the_token_file_wins_and_is_stripped(tmp_path: Path) -> None:
    path = tmp_path / "token"
    path.write_text(TOKEN + "\n")
    config = receiver.config_from_env(
        {"RECEIVER_TOKEN_FILE": str(path), "RECEIVER_TOKEN": "x" * 40}
    )
    assert config.token == TOKEN
    assert (config.host, config.port) == ("0.0.0.0", 8081)
    with pytest.raises(SystemExit):
        receiver.config_from_env({"RECEIVER_TOKEN": TOKEN, "RECEIVER_LISTEN": "8081"})


# -- units and paths


def test_put_serves_a_page_and_lists_it(server: Running) -> None:
    files = {**page(), "file-1-0123456789.pdf": b"%PDF-1.7"}
    status, payload = server.put("p/my-page", files)
    assert status == 200
    assert payload["digest"] == digest(files) and payload["files"] == 2
    www = server.site / "www"
    assert (www / "p/my-page/index.html").read_bytes() == b"<p>hello</p>"
    assert (www / "p/my-page/file-1-0123456789.pdf").read_bytes() == b"%PDF-1.7"
    assert (www / "p/my-page").is_symlink()
    status, manifest, _ = server.request("GET", "/v1/manifest")
    assert status == 200
    assert manifest["version"] == 1 and manifest["quota"] == 2 * 1024**3
    entry = manifest["units"]["p/my-page"]
    assert entry["digest"] == digest(files) and entry["files"] == 2
    # The content's bytes (the quota alone counts 4 KiB blocks)
    assert entry["bytes"] == len(b"<p>hello</p>") + 8 == manifest["bytes"]
    assert "charged" not in entry and "charged" not in payload
    assert entry["at"].endswith("Z")


@pytest.mark.parametrize(
    "unit", ["home", "pagefind", "assets", "t/maths", "p/" + "a" * 120]
)
def test_every_kind_of_unit(server: Running, unit: str) -> None:
    files = {
        "pagefind": {"pagefind.js": b"x", "wasm.en.pagefind": b"y"},
        "assets": {"katex.css": b"x", "fonts/KaTeX_Main.woff2": b"y"},
    }.get(unit, page())
    assert server.put(unit, files)[0] == 200
    assert (server.site / "www" / unit).is_symlink()


@pytest.mark.parametrize(
    ("unit", "name"),
    [
        ("p/x", "img-1-0123456789.jpg"),
        ("p/x", "img-20-abcdef0123.svg"),
        ("p/x", "file-3-0123456789.md"),
        ("p/x", "file-1-0123456789.bin"),
        ("home", "tags.html"),
        ("pagefind", "fragment/en_1.pf_fragment"),
        ("pagefind", "scrap-search.js"),
        ("assets", "fonts/KaTeX_Main.ttf"),
        ("assets", "prefs.js"),  # the public pages' one script (#519)
    ],
)
def test_each_kind_takes_its_own_files(server: Running, unit: str, name: str) -> None:
    files = {name: b"x"} | ({} if unit in ("pagefind", "assets") else page())
    assert server.put(unit, files)[0] == 200


@pytest.mark.parametrize(
    ("unit", "name"),
    [
        ("p/x", "files/report.pdf"),  # a folder
        ("p/x", "style.css"),
        ("p/x", "app.js"),
        ("p/x", "other.html"),
        ("p/x", "img-1-0123456789.gif"),
        ("p/x", "img-0-0123456789.jpg"),
        ("p/x", "img-1-0123456789a.jpg"),
        ("p/x", "img-1-ABCDEF0123.jpg"),
        ("p/x", "file-1-0123456789.html"),
        ("p/x", "file-1-0123456789.svg"),
        ("p/x", "file-1-0123456789.js"),
        ("p/x", "file-100-0123456789.pdf"),
        ("p/x", "report.pdf"),
        ("t/x", "style.css"),
        ("t/x", "more.html"),
        ("t/x", "page-2.html"),
        ("t/x", "a/b.html"),
        ("t/x", "img-1-0123456789.png"),
        ("home", "search.js"),
        ("home", "robots.txt"),
        ("home", "style.css"),
        ("pagefind", "pagefind-ui.css"),
        ("pagefind", "index.html"),
        ("assets", "katex.js"),
        ("assets", "index.html"),
        ("assets", "fonts/prefs.js"),  # prefs.js only at the top of assets
        ("assets", "PREFS.JS"),
        ("assets", "prefs.mjs"),
        ("p/x", "prefs.js"),  # and only in assets
        ("t/x", "prefs.js"),
        ("home", "prefs.js"),
    ],
)
def test_each_kind_refuses_other_files(server: Running, unit: str, name: str) -> None:
    files = {name: b"x"} | ({} if unit in ("pagefind", "assets") else page())
    status, payload = server.put(unit, files)
    assert (status, payload["error"]) == (422, "bad_member")


@pytest.mark.parametrize(
    "unit",
    [
        "p/..",
        "p/%2e%2e",
        "p/a%2fb",
        "p/Upper",
        "p/a/b",
        "p/.hidden",
        "p/a.b",
        "p/",
        "p/a/",
        "p//a",
        "p/" + "a" * 121,
        "t/" + "a" * 81,
        "t/a_b",
        "x/a",
        "home/",
        "Home",
        "home?x=1",
        "../home",
        "pagefind/x",
    ],
)
def test_bad_units_are_422(server: Running, unit: str) -> None:
    for method in ("PUT", "DELETE"):
        status, payload, _ = server.request(
            method,
            f"/v1/units/{unit}",
            b"",
            {"Content-Type": "application/x-tar"},
        )
        assert (status, payload["error"]) == (422, "bad_unit"), (method, unit)


@pytest.mark.parametrize("unit", [b"p/a\x00b", "p/caf\xc3\xa9".encode("latin-1")])
def test_nul_and_unicode_units_are_refused(server: Running, unit: bytes) -> None:
    response = server.raw(
        b"DELETE /v1/units/" + unit + b" HTTP/1.1\r\nHost: x\r\n"
        b"Authorization: Bearer " + TOKEN.encode() + b"\r\n\r\n"
    )
    assert status_of(response) in (400, 422)
    assert not any((server.site / "www" / "p").iterdir())


def test_unicode_unit_is_422(server: Running) -> None:
    response = server.raw(
        "DELETE /v1/units/p/café HTTP/1.1\r\n".encode()
        + b"Host: x\r\nAuthorization: Bearer "
        + TOKEN.encode()
        + b"\r\n\r\n"
    )
    assert status_of(response) == 422


# -- the tar's members


@pytest.mark.parametrize(
    "members",
    [
        [(member("a.js", tarfile.SYMTYPE, linkname="/etc/passwd"), None)],
        [
            (member("a.js"), b"x"),
            (member("b.js", tarfile.LNKTYPE, linkname="a.js"), None),
        ],
        [(member("a.js", tarfile.CHRTYPE, devmajor=1, devminor=3), None)],
        [(member("a.js", tarfile.FIFOTYPE), None)],
        [(member("a.js", tarfile.CONTTYPE), b"x")],
        [(member("files", tarfile.DIRTYPE), None), (member("a.js"), b"x")],
        [(member("a.js"), b"x"), (member("a.js"), b"y")],
        [(member("../a.js"), b"x")],
        [(member("/a.js"), b"x")],
        [(member("./a.js"), b"x")],
        [(member(".a.js"), b"x")],
        [(member("a/b/c/d/e.js"), b"x")],
        [(member("run.sh"), b"x")],
        [(member("noext"), b"x")],
        [(member("café.js"), b"x")],
        [(member("a.js"), b"x"), (member("a.js/b.js"), b"x")],
        [(member("a.js/b.js"), b"x"), (member("a.js"), b"x")],
    ],
)
def test_bad_members_are_refused(server: Running, members: list) -> None:
    status, payload = server.put_raw("pagefind", tar_of(*members), "0" * 64)
    assert (status, payload["error"]) == (422, "bad_member")
    assert not (server.site / "www/pagefind").exists()
    assert not any((server.site / "staging").iterdir())
    assert not any((server.site / "units").iterdir())


def test_a_unit_without_index_is_refused(server: Running) -> None:
    status, payload = server.put("p/x", {"img-1-0123456789.png": b"x"})
    assert (status, payload["error"]) == (422, "no_index")


def test_not_a_tar_is_400(server: Running) -> None:
    status, payload = server.put_raw("p/x", b"hello" * 200, "0" * 64)
    assert (status, payload["error"]) == (400, "bad_tar")


def test_a_file_over_the_limit_is_413(tmp_path: Path) -> None:
    running = Running(tmp_path / "site", max_file=100)
    try:
        assert running.put("p/x", {"index.html": b"x" * 100})[0] == 200
        status, payload = running.put("p/y", {"index.html": b"x" * 101})
        assert (status, payload["error"]) == (413, "file_too_large")
    finally:
        running.stop()


def test_too_many_files_is_413(tmp_path: Path) -> None:
    running = Running(tmp_path / "site", max_files=3)
    try:
        files = {f"{i}.html": b"x" for i in range(3)} | page()
        status, payload = running.put("home", files)
        assert (status, payload["error"]) == (413, "too_many_files")
    finally:
        running.stop()


def test_build_unit_refuses_what_the_receiver_would() -> None:
    for bad in [{}, {"../x.html": b""}, {"a/b/c/d/e.html": b""}, {".x.html": b""}]:
        with pytest.raises(UnitError):
            build_unit(bad)


# -- headers, limits, digest, quota


def test_digest_mismatch_is_400_and_changes_nothing(server: Running) -> None:
    assert server.put("p/x", page("one"))[0] == 200
    tar, _ = build_unit(page("two"))
    status, payload = server.put_raw("p/x", tar, digest(page("three")))
    assert (status, payload["error"]) == (400, "digest_mismatch")
    status, payload = server.put_raw("p/x", tar, "")
    assert status == 400
    assert (server.site / "www/p/x/index.html").read_bytes() == b"<p>one</p>"
    assert len(list((server.site / "units").iterdir())) == 2  # one dir, one json


def test_no_content_length_is_411(server: Running) -> None:
    response = server.raw(
        b"PUT /v1/units/p/x HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-tar\r\n"
        b"Authorization: Bearer " + TOKEN.encode() + b"\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
    )
    assert status_of(response) == 411
    response = server.raw(
        b"PUT /v1/units/p/x HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-tar\r\n"
        b"Authorization: Bearer " + TOKEN.encode() + b"\r\n\r\n"
    )
    assert status_of(response) == 411


def test_too_large_is_413_before_the_body_is_read(server: Running) -> None:
    # Headers only: the answer must come without the client sending a byte of body
    start = time.monotonic()
    response = server.raw(
        b"PUT /v1/units/p/x HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-tar\r\n"
        b"Authorization: Bearer " + TOKEN.encode() + b"\r\n"
        b"Content-Length: " + str(257 * 1024 * 1024).encode() + b"\r\n\r\n"
    )
    assert status_of(response) == 413
    assert b'"body_too_large"' in response
    assert time.monotonic() - start < 4


def test_expect_continue_gets_the_refusal_not_100(server: Running) -> None:
    response = server.raw(
        b"PUT /v1/units/p/x HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-tar\r\n"
        b"Authorization: Bearer " + TOKEN.encode() + b"\r\nExpect: 100-continue\r\n"
        b"Content-Length: " + str(300 * 1024 * 1024).encode() + b"\r\n\r\n"
    )
    assert response.startswith(b"HTTP/1.1 413")


def test_wrong_content_type_is_415(server: Running) -> None:
    tar, dig = build_unit(page())
    status, payload, _ = server.request(
        "PUT",
        "/v1/units/p/x",
        tar,
        {"Content-Type": "application/gzip", "Scrap-Digest": dig},
    )
    assert (status, payload["error"]) == (415, "unsupported_media_type")
    status, _, _ = server.request(
        "POST", "/v1/sync", b'{"keep":["home"]}', {"Content-Type": "text/plain"}
    )
    assert status == 415


def test_over_the_quota_is_507(tmp_path: Path) -> None:
    # Files count as whole 4 KiB blocks, at least one each: 3 blocks hold 3 pages
    # of 1, 4096 and 0 bytes, and not a fourth
    running = Running(tmp_path / "site", quota=3 * 4096)
    try:
        assert running.put("p/a", {"index.html": b"x"})[0] == 200
        assert running.put("p/b", {"index.html": b"x" * 4096})[0] == 200
        assert running.put("p/c", {"index.html": b""})[0] == 200
        status, payload = running.put("p/d", {"index.html": b"x"})
        assert (status, payload["error"]) == (507, "over_quota")
        assert running.put("p/b", {"index.html": b"x" * 4097})[0] == 507
        # Replacing a unit counts its new size, not both
        assert running.put("p/b", {"index.html": b"y" * 4096})[0] == 200
        manifest = running.request("GET", "/v1/manifest")[1]
        assert manifest["bytes"] == 1 + 4096 + 0
        assert not any((tmp_path / "site/staging").iterdir())
    finally:
        running.stop()


def test_a_second_writer_gets_503(server: Running) -> None:
    tar, dig = build_unit(page())
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as slow:
        slow.sendall(
            b"PUT /v1/units/p/slow HTTP/1.1\r\nHost: x\r\n"
            b"Content-Type: application/x-tar\r\nScrap-Digest: "
            + dig.encode()
            + b"\r\n"
            b"Authorization: Bearer " + TOKEN.encode() + b"\r\n"
            b"Content-Length: " + str(len(tar)).encode() + b"\r\n\r\n" + tar[:100]
        )
        for _ in range(100):  # until the slow upload holds the lock
            if server.server.site.write_lock.locked():
                break
            time.sleep(0.01)
        status, payload, headers = server.request("DELETE", "/v1/units/p/other")
        assert (status, payload["error"]) == (503, "busy")
        assert headers["Retry-After"] == "1"
        assert server.put("p/other", page())[0] == 503
        slow.sendall(tar[100:])
        assert slow.recv(100).startswith(b"HTTP/1.1 200")
    assert server.put("p/other", page())[0] == 200


def test_a_stalled_upload_times_out(tmp_path: Path) -> None:
    running = Running(tmp_path / "site", timeout=0.5)
    try:
        tar, dig = build_unit(page())
        response = running.raw(
            b"PUT /v1/units/p/x HTTP/1.1\r\nHost: x\r\n"
            b"Content-Type: application/x-tar\r\nScrap-Digest: "
            + dig.encode()
            + b"\r\n"
            b"Authorization: Bearer " + TOKEN.encode() + b"\r\n"
            b"Content-Length: " + str(len(tar)).encode() + b"\r\n\r\n" + tar[:600]
        )
        assert status_of(response) == 408
        assert not running.server.site.write_lock.locked()
        assert not any((tmp_path / "site/staging").iterdir())
    finally:
        running.stop()


def test_wrong_methods_are_405(server: Running) -> None:
    status, payload, headers = server.request("GET", "/v1/units/home")
    assert (status, headers["Allow"]) == (405, "PUT, DELETE")
    assert server.request("PUT", "/v1/manifest", b"")[0] == 405
    assert server.request("GET", "/v1/sync")[0] == 405


# -- the swap


def test_a_reader_never_sees_a_missing_or_mixed_page(server: Running) -> None:
    versions = {
        n: {
            "index.html": (str(n) * 20000).encode(),
            "img-1-0123456789.svg": (str(n) * 5000).encode(),
        }
        for n in range(10)
    }
    assert server.put("p/live", versions[0])[0] == 200
    index = server.site / "www/p/live/index.html"
    css = server.site / "www/p/live/img-1-0123456789.svg"
    wholes = {v["index.html"] for v in versions.values()}
    css_wholes = {v["img-1-0123456789.svg"] for v in versions.values()}
    problems: list[str] = []
    stop = threading.Event()

    def read() -> None:
        while not stop.is_set():
            try:
                data, style = index.read_bytes(), css.read_bytes()
            except OSError as error:
                problems.append(f"missing: {error}")
                continue
            if data not in wholes or style not in css_wholes:
                problems.append("mixed within a file")

    readers = [threading.Thread(target=read) for _ in range(3)]
    for t in readers:
        t.start()
    try:
        for n in list(range(1, 10)) * 3:
            assert server.put("p/live", versions[n])[0] == 200
    finally:
        stop.set()
        for t in readers:
            t.join()
    assert problems == []
    assert index.read_bytes() == versions[9]["index.html"]
    # Only the live copy is left
    assert len(list((server.site / "units").iterdir())) == 2


# -- delete and sync


def test_delete_is_idempotent(server: Running) -> None:
    assert server.put("p/x", page())[0] == 200
    for _ in range(2):
        status, payload, _ = server.request("DELETE", "/v1/units/p/x")
        assert (status, payload) == (204, {})
    assert not (server.site / "www/p/x").exists()
    assert not any((server.site / "units").iterdir())
    assert server.request("GET", "/v1/manifest")[1]["units"] == {}


def sync(server: Running, body) -> tuple[int, dict]:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    status, payload, _ = server.request(
        "POST", "/v1/sync", raw, {"Content-Type": "application/json"}
    )
    return status, payload


def test_sync_deletes_what_is_not_kept(server: Running) -> None:
    for unit in ["home", "p/a", "p/b", "t/c"]:
        assert server.put(unit, page())[0] == 200
    status, payload = sync(server, {"keep": ["home", "p/a", "p/gone"]})
    assert (status, payload) == (200, {"deleted": ["p/b", "t/c"]})
    assert sorted(server.request("GET", "/v1/manifest")[1]["units"]) == ["home", "p/a"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"keep": []}, 422),
        ({"keep": ["p/a"]}, 422),
        ({"keep": ["home", "p/../x"]}, 422),
        ({"keep": "home"}, 400),
        ({"keep": ["home", 3]}, 400),
        ({}, 400),
        (b"not json", 400),
    ],
)
def test_sync_guards(server: Running, body, status: int) -> None:
    assert server.put("p/a", page())[0] == 200
    assert sync(server, body)[0] == status
    assert "p/a" in server.request("GET", "/v1/manifest")[1]["units"]


# -- startup


def test_startup_cleans_staging_and_unreferenced_units(tmp_path: Path) -> None:
    site = tmp_path / "site"
    running = Running(site)
    try:
        assert running.put("p/keep", page())[0] == 200
        assert running.put("home", page())[0] == 200
    finally:
        running.stop()
    (site / "staging/abc").mkdir()
    (site / "staging/abc/index.html").write_text("half")
    (site / "units/deadbeef").mkdir()
    (site / "units/deadbeef.json").write_text("{}")
    (site / "www/p/dangling").symlink_to("../../units/missing")
    (site / "www/p/notalink").mkdir()
    (site / "www/stray.html").write_text("x")
    running = Running(site)
    try:
        assert not any((site / "staging").iterdir())
        assert not (site / "units/deadbeef").exists()
        assert not (site / "units/deadbeef.json").exists()
        assert not (site / "www/p/dangling").is_symlink()
        assert not (site / "www/p/notalink").exists()
        assert not (site / "www/stray.html").exists()
        units = running.request("GET", "/v1/manifest")[1]["units"]
        assert sorted(units) == ["home", "p/keep"]
        assert (site / "www/p/keep/index.html").read_bytes() == b"<p>hello</p>"
        assert len(list((site / "units").iterdir())) == 4
    finally:
        running.stop()


def test_sync_keeps_assets_and_pagefind(server: Running) -> None:
    assert server.put("home", page())[0] == 200
    assert server.put("assets", {"katex.css": b"x"})[0] == 200
    assert server.put("pagefind", {"pagefind.js": b"x"})[0] == 200
    status, payload = sync(server, {"keep": ["home", "assets", "pagefind"]})
    assert (status, payload) == (200, {"deleted": []})
    assert sync(server, {"keep": ["home"]})[1] == {"deleted": ["assets", "pagefind"]}


# -- review probes: header blocks, deadlines, early refusals, signals, disk errors


def test_a_large_pax_header_is_refused_before_it_is_read(server: Running) -> None:
    info = member("index.html")
    info.pax_headers = {"comment": "x" * (65 * 1024)}
    status, payload = server.put_raw("p/x", tar_of((info, b"x")), "0" * 64)
    assert (status, payload["error"]) == (400, "bad_tar")
    assert "64 KiB" in payload["detail"]


def test_a_gnu_long_name_is_refused(server: Running) -> None:
    # Any GNU header type: only pax and ustar are taken
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as tar:
        info = tarfile.TarInfo("a" * 200 + ".html")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    status, payload = server.put_raw("p/x", buffer.getvalue(), "0" * 64)
    assert (status, payload["error"]) == (400, "bad_tar")


def test_a_small_pax_header_is_fine(server: Running) -> None:
    info = member("index.html")
    info.pax_headers = {"comment": "x" * 1000}
    content = b"<p>x</p>"
    status, _ = server.put_raw(
        "p/x", tar_of((info, content)), digest({"index.html": content})
    )
    assert status == 200


def put_head(length: int, dig: str = "0" * 64) -> bytes:
    return (
        b"PUT /v1/units/p/x HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-tar\r\n"
        b"Scrap-Digest: " + dig.encode() + b"\r\n"
        b"Authorization: Bearer " + TOKEN.encode() + b"\r\n"
        b"Content-Length: " + str(length).encode() + b"\r\n\r\n"
    )


def read_reply(s: socket.socket) -> bytes:
    got = b""
    try:
        while chunk := s.recv(65536):
            got += chunk
    except (TimeoutError, ConnectionError):
        pass
    return got


def test_a_dribbled_body_meets_the_deadline(tmp_path: Path) -> None:
    # Each byte comes well within any per-read timeout; the request's deadline
    # still ends it, and the lock is free after
    running = Running(tmp_path / "site", timeout=1.0)
    try:
        tar, dig = build_unit(page())
        start = time.monotonic()
        with socket.create_connection(("127.0.0.1", running.port), timeout=5) as s:
            s.sendall(put_head(len(tar), dig))
            got = b""
            for byte in tar[:40]:
                try:
                    s.sendall(bytes([byte]))
                except OSError:
                    break
                time.sleep(0.1)
                if time.monotonic() - start > 3:
                    break
            got = read_reply(s)
        assert got.startswith(b"HTTP/1.1 408")
        assert time.monotonic() - start < 4
        assert not running.server.site.write_lock.locked()
        assert running.put("p/x", page())[0] == 200
    finally:
        running.stop()


def test_dribbled_headers_meet_the_deadline(tmp_path: Path) -> None:
    running = Running(tmp_path / "site", timeout=1.0)
    try:
        start = time.monotonic()
        with socket.create_connection(("127.0.0.1", running.port), timeout=5) as s:
            closed = False
            for byte in b"GET /healthz HTTP/1.1\r\nX-Slow: " + b"a" * 100:
                try:
                    s.sendall(bytes([byte]))
                except OSError:
                    closed = True
                    break
                time.sleep(0.05)
                if time.monotonic() - start > 3:
                    break
            if not closed:
                s.settimeout(2)
                got = read_reply(s)
                assert got.startswith(b"HTTP/1.1 408"), got[:80]
                assert b'"timeout"' in got
        assert time.monotonic() - start < 4
    finally:
        running.stop()


def test_an_early_refusal_reaches_a_client_still_sending(server: Running) -> None:
    # 413 from the headers while the client goes on sending its body: the server
    # stops writing and drains, so the client reads the answer, not a reset
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as s:
        s.sendall(put_head(300 * 1024 * 1024))
        try:
            for _ in range(64):
                s.sendall(b"\0" * 65536)
        except OSError:
            pass
        s.shutdown(socket.SHUT_WR)
        got = read_reply(s)
    assert got.startswith(b"HTTP/1.1 413"), got[:80]


def test_a_get_with_a_body_closes_the_connection(server: Running) -> None:
    response = server.raw(
        b"GET /v1/manifest HTTP/1.1\r\nHost: x\r\n"
        b"Authorization: Bearer " + TOKEN.encode() + b"\r\n"
        b"Content-Length: 5\r\n\r\nhello"
    )
    assert response.startswith(b"HTTP/1.1 200")
    assert b"Connection: close" in response


@pytest.mark.parametrize("length", ["١٢", "1e3", "-1", "+5", " "])
def test_content_length_takes_ascii_digits_only(server: Running, length: str) -> None:
    response = server.raw(
        b"PUT /v1/units/p/x HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-tar\r\n"
        b"Authorization: Bearer " + TOKEN.encode() + b"\r\n"
        b"Content-Length: " + length.encode() + b"\r\n\r\n"
    )
    assert status_of(response) in (400, 411)


def test_the_quota_setting_takes_ascii_digits_only() -> None:
    env = {"RECEIVER_TOKEN": TOKEN}
    assert (
        receiver.config_from_env(env | {"RECEIVER_QUOTA_BYTES": "4096"}).quota == 4096
    )
    with pytest.raises(SystemExit):
        receiver.config_from_env(env | {"RECEIVER_QUOTA_BYTES": "١٢"})


def test_a_full_disk_is_507(server: Running, monkeypatch: pytest.MonkeyPatch) -> None:
    def full(*_args) -> str:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(receiver, "_write", full)
    status, payload = server.put("p/x", page())
    assert (status, payload["error"]) == (507, "over_quota")
    assert not server.server.site.write_lock.locked()
    assert not any((server.site / "staging").iterdir())


def test_another_write_error_is_500(
    server: Running, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args) -> str:
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(receiver, "_write", broken)
    status, payload = server.put("p/x", page())
    assert (status, payload["error"]) == (500, "server_error")


def test_sigterm_stops_the_receiver_cleanly(tmp_path: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {
        "RECEIVER_TOKEN": TOKEN,
        "RECEIVER_SITE": str(tmp_path / "site"),
        "RECEIVER_LISTEN": f"tcp:127.0.0.1:{port}",
        "PATH": "/usr/bin:/bin",
    }
    process = subprocess.Popen(
        [sys.executable, "-I", str(ROOT / "scrap-public" / "receiver.py")],
        env=env,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.05)
        process.send_signal(signal.SIGTERM)
        _, err = process.communicate(timeout=10)
        assert process.returncode == 0
        assert "SIGTERM, stopping" in err
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_a_pax_sparse_member_is_refused(server: Running) -> None:
    # A regular-file header that pax marks sparse (GNU sparse 0.1)
    info = member("a.js")
    info.pax_headers = {
        "GNU.sparse.map": "0,1",
        "GNU.sparse.size": "1",
        "GNU.sparse.name": "a.js",
    }
    status, payload = server.put_raw("pagefind", tar_of((info, b"x")), "0" * 64)
    assert (status, payload["error"]) == (400, "bad_tar")
    assert "sparse" in payload["detail"]


# -- round 3 probes: GNU and sparse headers, meta runs, unexpected errors, JSON
# errors before anything, the deadline and the lock


def _header(info: tarfile.TarInfo, extended: bool = False) -> bytearray:
    """A ustar header block for info, with the GNU 'isextended' flag if asked."""
    block = bytearray(info.tobuf(tarfile.USTAR_FORMAT, "utf-8", "surrogateescape"))
    if extended:
        block[482] = 1
        block[148:156] = b" " * 8
        block[148:156] = b"%06o\0 " % sum(block[:512])
    return block


def _end() -> bytes:
    return b"\0" * 1024


def test_a_gnu_sparse_header_with_many_blocks_is_refused_cheaply(
    server: Running,
) -> None:
    # 'S' with 20,000 extension blocks: tarfile would read every one into a list
    info = tarfile.TarInfo("a.js")
    info.type = tarfile.GNUTYPE_SPARSE
    blocks = (b"\0" * 504 + b"\1" + b"\0" * 7) * 20_000
    body = bytes(_header(info, extended=True)) + blocks + _end()
    tracemalloc.start()
    try:
        status, payload = server.put_raw("pagefind", body, "0" * 64)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert (status, payload["error"]) == (400, "bad_tar")
    assert "GNU" in payload["detail"]
    assert peak < 8 * 1024 * 1024


def test_a_large_pax_sparse_map_is_refused_cheaply(server: Running) -> None:
    # GNU sparse 1.0 keeps its map in the member's data: a map of a million
    # entries is never read
    info = member("a.js")
    info.pax_headers = {
        "GNU.sparse.major": "1",
        "GNU.sparse.minor": "0",
        "GNU.sparse.name": "a.js",
        "GNU.sparse.realsize": "1",
    }
    sparse_map = b"1000000\n" + b"0\n1\n" * 1_000_000
    body = tar_of((info, sparse_map))
    tracemalloc.start()
    try:
        status, payload = server.put_raw("pagefind", body, "0" * 64)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert (status, payload["error"]) == (400, "bad_tar")
    assert "sparse" in payload["detail"]
    assert peak < 8 * 1024 * 1024


def _pax_block(record: bytes) -> bytes:
    info = tarfile.TarInfo("PaxHeader")
    info.type = tarfile.XHDTYPE
    info.size = len(record)
    padded = record + b"\0" * (-len(record) % 512)
    return bytes(_header(info)) + padded


def _pax_record(key: str, value: str) -> bytes:
    body = f" {key}={value}\n"
    n = len(body) + 1
    while len(str(n)) + len(body) != n:
        n += 1
    return f"{n}{body}".encode()


@pytest.mark.parametrize(
    ("run", "status"), [(2, 200), (32, 200), (33, 400), (500, 400)]
)
def test_a_run_of_pax_headers_is_capped(server: Running, run: int, status: int) -> None:
    content = b"<p>x</p>"
    info = member("index.html")
    info.size = len(content)
    body = b"".join(_pax_block(_pax_record("comment", "x")) for _ in range(run))
    body += bytes(_header(info)) + content + b"\0" * (512 - len(content)) + _end()
    got, payload = server.put_raw("p/x", body, digest({"index.html": content}))
    assert got == status, payload
    if status == 400:
        assert payload["error"] == "bad_tar"


def test_an_unexpected_error_is_a_json_500(
    server: Running, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args) -> str:
        raise ValueError("unexpected")

    monkeypatch.setattr(receiver, "unit_digest", boom)
    tar, dig = build_unit(page())
    response = server.raw(put_head(len(tar), dig) + tar)
    assert response.startswith(b"HTTP/1.1 500")
    assert b'"server_error"' in response and b"Connection: close" in response
    assert not server.server.site.write_lock.locked()


@pytest.mark.parametrize("method", [b"OPTIONS", b"BREW", b"PATCH", b"TRACE"])
def test_any_method_without_the_token_is_401(server: Running, method: bytes) -> None:
    response = server.raw(method + b" /v1/manifest HTTP/1.1\r\nHost: x\r\n\r\n")
    assert response.startswith(b"HTTP/1.1 401")
    assert b'"unauthorized"' in response


@pytest.mark.parametrize("method", [b"OPTIONS", b"BREW"])
def test_any_method_with_the_token_is_405(server: Running, method: bytes) -> None:
    response = server.raw(
        method + b" /v1/manifest HTTP/1.1\r\nHost: x\r\n"
        b"Authorization: Bearer " + TOKEN.encode() + b"\r\n\r\n"
    )
    assert response.startswith(b"HTTP/1.1 405")
    assert b'"method_not_allowed"' in response


@pytest.mark.parametrize(
    ("request_bytes", "status"),
    [
        (b"NONSENSE\r\n\r\n", 400),
        (b"GET /healthz HTTP/9.9\r\n\r\n", 505),
        (b"GET /healthz HTTP/1.1\r\nX: " + b"a" * 70_000 + b"\r\n\r\n", 431),
        (b"GET /" + b"a" * 70_000 + b" HTTP/1.1\r\n\r\n", 414),
    ],
)
def test_malformed_requests_get_json(
    server: Running, request_bytes: bytes, status: int
) -> None:
    response = server.raw(request_bytes)
    assert status_of(response) == status
    head, _, body = response.partition(b"\r\n\r\n")
    assert b"Content-Type: application/json" in head
    assert "error" in json.loads(body)


def test_fsync_after_the_body_is_not_held_to_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 400 files whose fsyncs take 2 s in all, with a 1 s deadline: the body
    # arrives in time, so the upload succeeds
    real = receiver._fsync_file

    def slow(path: Path) -> None:
        time.sleep(0.005)
        real(path)

    monkeypatch.setattr(receiver, "_fsync_file", slow)
    running = Running(tmp_path / "site", timeout=1.0)
    try:
        files = {f"fragment/f{i}.pf_fragment": b"x" for i in range(400)}
        start = time.monotonic()
        status, payload = running.put("pagefind", files)
        assert status == 200, payload
        assert time.monotonic() - start > 1.5
        assert payload["files"] == 400
    finally:
        running.stop()


def test_busy_is_answered_before_100_continue(server: Running) -> None:
    server.server.site.write_lock.acquire()
    try:
        tar, dig = build_unit(page())
        head = put_head(len(tar), dig).replace(
            b"\r\n\r\n", b"\r\nExpect: 100-continue\r\n\r\n"
        )
        response = server.raw(head)
        assert response.startswith(b"HTTP/1.1 503"), response[:80]
        assert b"Retry-After: 1" in response
    finally:
        server.server.site.write_lock.release()


def test_100_continue_holds_the_lock_for_the_upload(server: Running) -> None:
    tar, dig = build_unit(page())
    head = put_head(len(tar), dig).replace(
        b"\r\n\r\n", b"\r\nExpect: 100-continue\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as s:
        s.sendall(head)
        assert s.recv(100).startswith(b"HTTP/1.1 100")
        assert server.server.site.write_lock.locked()
        assert server.request("DELETE", "/v1/units/p/y")[0] == 503
        s.sendall(tar)
        assert s.recv(100).startswith(b"HTTP/1.1 200")
    for _ in range(100):
        if not server.server.site.write_lock.locked():
            break
        time.sleep(0.01)
    assert not server.server.site.write_lock.locked()


def test_the_tarfile_hooks_are_checked() -> None:
    receiver.check_tarfile()

    class Bare:
        pass

    with pytest.raises(SystemExit, match="_proc_member"):
        receiver.check_tarfile(Bare)
