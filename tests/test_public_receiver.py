"""scrap-public/receiver.py, run on a free port over a temporary site folder, with
uploads built by scrap.publish.unit (as scrap's client builds them)."""

import importlib.util
import io
import json
import socket
import sys
import tarfile
import threading
import time
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
    files = {**page(), "files/report.pdf": b"%PDF-1.7"}
    status, payload = server.put("p/my-page", files)
    assert status == 200
    assert payload["digest"] == digest(files) and payload["files"] == 2
    www = server.site / "www"
    assert (www / "p/my-page/index.html").read_bytes() == b"<p>hello</p>"
    assert (www / "p/my-page/files/report.pdf").read_bytes() == b"%PDF-1.7"
    assert (www / "p/my-page").is_symlink()
    status, manifest, _ = server.request("GET", "/v1/manifest")
    assert status == 200
    assert manifest["version"] == 1 and manifest["quota"] == 2 * 1024**3
    entry = manifest["units"]["p/my-page"]
    assert entry["digest"] == digest(files) and entry["files"] == 2
    assert entry["bytes"] == len(b"<p>hello</p>") + 8 == manifest["bytes"]
    assert entry["at"].endswith("Z")


@pytest.mark.parametrize("unit", ["home", "pagefind", "t/maths", "p/" + "a" * 120])
def test_every_kind_of_unit(server: Running, unit: str) -> None:
    files = (
        page()
        if unit != "pagefind"
        else {"pagefind.js": b"x", "wasm.en.pagefind": b"y"}
    )
    assert server.put(unit, files)[0] == 200
    assert (server.site / "www" / unit).is_symlink()


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
        [(member("index.html", tarfile.SYMTYPE, linkname="/etc/passwd"), None)],
        [
            (member("a.html"), b"x"),
            (member("index.html", tarfile.LNKTYPE, linkname="a.html"), None),
        ],
        [(member("index.html", tarfile.CHRTYPE, devmajor=1, devminor=3), None)],
        [(member("index.html", tarfile.FIFOTYPE), None)],
        [(member("files", tarfile.DIRTYPE), None), (member("index.html"), b"x")],
        [(member("index.html"), b"x"), (member("index.html"), b"y")],
        [(member("../index.html"), b"x")],
        [(member("/index.html"), b"x")],
        [(member("./index.html"), b"x")],
        [(member(".index.html"), b"x")],
        [(member("index.html"), b"x"), (member("a/b/c/d/e.html"), b"x")],
        [(member("index.html"), b"x"), (member("run.sh"), b"x")],
        [(member("index.html"), b"x"), (member("noext"), b"x")],
        [(member("index.html"), b"x"), (member("café.html"), b"x")],
        [(member("index.html"), b"x"), (member("a"), b"x"), (member("a/b.html"), b"x")],
        [(member("index.html"), b"x"), (member("a/b.html"), b"x"), (member("a"), b"x")],
    ],
)
def test_bad_members_are_refused(server: Running, members: list) -> None:
    status, payload = server.put_raw("p/x", tar_of(*members), "0" * 64)
    assert (status, payload["error"]) == (422, "bad_member")
    assert not (server.site / "www/p/x").exists()
    assert not any((server.site / "staging").iterdir())
    assert not any((server.site / "units").iterdir())


def test_a_unit_without_index_is_refused(server: Running) -> None:
    status, payload = server.put("p/x", {"style.css": b"x"})
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
        status, payload = running.put("p/x", files)
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
    running = Running(tmp_path / "site", quota=1000)
    try:
        assert running.put("p/a", {"index.html": b"x" * 600})[0] == 200
        status, payload = running.put("p/b", {"index.html": b"x" * 500})
        assert (status, payload["error"]) == (507, "over_quota")
        # Replacing a unit counts its new size, not both
        assert running.put("p/a", {"index.html": b"y" * 900})[0] == 200
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
        n: {"index.html": (str(n) * 20000).encode(), "a.css": (str(n) * 5000).encode()}
        for n in range(10)
    }
    assert server.put("p/live", versions[0])[0] == 200
    index = server.site / "www/p/live/index.html"
    css = server.site / "www/p/live/a.css"
    wholes = {v["index.html"] for v in versions.values()}
    css_wholes = {v["a.css"] for v in versions.values()}
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
