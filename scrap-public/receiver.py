"""scrap-public's upload receiver: scrap pushes the public site here, one unit at a
time (a page, a tag page, the home page, the search index, the shared assets), as
a tar.

Internal only: it needs a bearer token on every route but /healthz, and it only
ever writes or deletes inside the site folder. Stdlib only. The contract is
docs/reference/public-site.md.

The site folder (RECEIVER_SITE, default /site) holds:

- ``www/``: what nginx serves, read only. Each unit is a symlink there
  (``www/p/<slug>``, ``www/t/<key>``, ``www/home``, ``www/pagefind``,
  ``www/assets``) to its copy.
- ``units/<id>/`` and ``units/<id>.json``: each unit's files and its manifest entry.
- ``staging/``: uploads being unpacked.

nginx's root is ``www/``, so ``units/`` and ``staging/`` are never served.

An upload is unpacked into staging member by member (never extractall), checked,
fsynced and moved into ``units/``; then a new symlink replaces the unit's old one
with ``os.replace`` (atomic), and the old copy is removed. A reader sees the old
unit or the new one, never a mix or nothing. One lock serialises the writes.
"""

from __future__ import annotations

import errno
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import signal
import socket
import sys
import tarfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MiB = 1024 * 1024
GiB = 1024 * MiB
MIN_TOKEN = 32

# Units, matched on the raw request path: no decoding, so %, ., // and a trailing
# / never match
UNIT = re.compile(r"(p/[a-z0-9-]{1,120}|t/[a-z0-9-]{1,80}|home|pagefind|assets)")
UNITS_PREFIX = "/v1/units/"
# The units at the top of www/ (the others are under www/p/ and www/t/)
TOP_UNITS = ("home", "pagefind", "assets")
# The units that must hold an index.html (nginx serves it for the unit's URL)
NEEDS_INDEX = ("p/", "t/", "home")
SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
MAX_DEPTH = 4
# What each kind of unit may hold. A page: its index.html, images and attachments,
# one segment each. A tag and home: HTML only. Scripts and WebAssembly only in
# pagefind, CSS and fonts only in assets.
PAGE_MEMBER = re.compile(
    r"index\.html"
    r"|img-[1-9][0-9]?-[0-9a-f]{10}\.(?:jpg|png|svg)"
    r"|file-[1-9][0-9]?-[0-9a-f]{10}"
    r"\.(?:pdf|txt|md|csv|zip|epub|docx|xlsx|pptx|odt|ods|odp|bin)"
)
PAGEFIND_TYPES = frozenset(
    {"js", "mjs", "json", "wasm", "pagefind", "pf_meta", "pf_index", "pf_fragment",
     "pf_filter"}
)  # fmt: skip
ASSETS_TYPES = frozenset({"css", "woff", "woff2", "ttf"})
TAR_TYPES = "application/x-tar"
CHUNK = 64 * 1024
# A pax or GNU long-name header block is read into memory whole: none may be larger
MAX_META = 64 * 1024
META_TYPES = (
    tarfile.XHDTYPE,
    tarfile.XGLTYPE,
    tarfile.SOLARIS_XHDTYPE,
    tarfile.GNUTYPE_LONGNAME,
    tarfile.GNUTYPE_LONGLINK,
)
# The quota counts each file as the disk does: whole 4 KiB blocks, at least one
BLOCK = 4096
# After an early refusal: how long, and how much, to read and discard so the client
# sees the answer instead of a reset
LINGER_SECONDS = 2.0
LINGER_BYTES = 16 * MiB
WRITE_TIMEOUT = 10.0


class Refusal(Exception):  # noqa: N818 (an answer, not a fault)
    """A request the receiver answers with an error: status, code and detail."""

    def __init__(self, status: int, error: str, detail: str, **headers: str) -> None:
        super().__init__(detail)
        self.status, self.error, self.detail = status, error, detail
        self.headers = headers


@dataclass
class Config:
    site: Path
    token: str
    host: str = "0.0.0.0"
    port: int = 8081
    quota: int = 2 * GiB
    max_body: int = 256 * MiB
    max_file: int = 20 * MiB
    max_files: int = 10_000
    timeout: float = 30.0


def digits(value: str) -> bool:
    """ASCII digits only (str.isdigit also takes other scripts' digits)."""
    return value.isascii() and value.isdigit()


def charged(size: int) -> int:
    """The bytes a file of ``size`` counts against the quota."""
    return max(BLOCK, -(-size // BLOCK) * BLOCK)


def member_allowed(unit: str, parts: list[str]) -> bool:
    """Whether a unit of this kind may hold a file at this path."""
    leaf = parts[-1]
    ext = leaf.rpartition(".")[2].lower() if "." in leaf else ""
    if unit.startswith("p/"):
        return len(parts) == 1 and PAGE_MEMBER.fullmatch(leaf) is not None
    if unit.startswith("t/") or unit == "home":
        return len(parts) == 1 and ext == "html"
    if unit == "pagefind":
        return ext in PAGEFIND_TYPES
    return ext in ASSETS_TYPES


def load_token(environ: dict[str, str]) -> str:
    """RECEIVER_TOKEN_FILE (its content, stripped) if set, else RECEIVER_TOKEN.
    Missing, shorter than MIN_TOKEN or holding whitespace: refuse to start."""
    if path := environ.get("RECEIVER_TOKEN_FILE"):
        try:
            token = Path(path).read_text(encoding="utf-8-sig").strip()
        except OSError as error:
            raise SystemExit(
                f"RECEIVER_TOKEN_FILE: cannot read {path!r}: {error.strerror}"
            ) from None
    else:
        token = environ.get("RECEIVER_TOKEN", "").strip()
    if len(token) < MIN_TOKEN or any(c.isspace() for c in token):
        raise SystemExit(
            f"RECEIVER_TOKEN(_FILE) must be one token of at least {MIN_TOKEN}"
            " characters, with no spaces"
        )
    return token


def parse_listen(value: str) -> tuple[str, int]:
    """RECEIVER_LISTEN: tcp:HOST:PORT (the only form so far)."""
    kind, _, rest = value.partition(":")
    host, _, port = rest.rpartition(":")
    if kind != "tcp" or not host or not digits(port):
        raise SystemExit(f"RECEIVER_LISTEN: expected tcp:HOST:PORT, got {value!r}")
    return host.strip("[]"), int(port)


def config_from_env(environ: dict[str, str]) -> Config:
    host, port = parse_listen(environ.get("RECEIVER_LISTEN", "tcp:0.0.0.0:8081"))
    quota = environ.get("RECEIVER_QUOTA_BYTES", "")
    if quota and not digits(quota):
        raise SystemExit(f"RECEIVER_QUOTA_BYTES: not a number of bytes: {quota!r}")
    return Config(
        site=Path(environ.get("RECEIVER_SITE", "/site")),
        token=load_token(environ),
        host=host,
        port=port,
        **({"quota": int(quota)} if quota else {}),
    )


def unit_digest(hashes: dict[str, str]) -> str:
    """The Scrap-Digest: sha256 of ``path NUL sha256hex LF`` in sorted path order."""
    lines = b"".join(
        path.encode() + b"\0" + hashes[path].encode() + b"\n" for path in sorted(hashes)
    )
    return hashlib.sha256(lines).hexdigest()


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Wire:
    """A connection's input, with one deadline for the whole request: its headers
    and its body. Before each read the socket's timeout is set to the time left,
    so a client dribbling a byte at a time cannot stretch a request past it.
    Between requests, the wait for the next one has the idle timeout instead."""

    def __init__(self, buffered, sock: socket.socket, idle: float) -> None:
        self.buffered, self.sock, self.idle = buffered, sock, idle
        self.deadline: float | None = None

    def start(self, seconds: float) -> None:
        self.deadline = time.monotonic() + seconds

    def _arm(self) -> None:
        if self.deadline is None:
            self.sock.settimeout(self.idle)
            return
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("the request's deadline passed")
        self.sock.settimeout(left)

    def wait(self) -> bytes:
        """Wait (idle) for the next request's first byte, without consuming it."""
        self.deadline = None
        self._arm()
        return self.buffered.peek(1)

    def read1(self, size: int = -1) -> bytes:
        self._arm()
        return self.buffered.read1(size if size and size > 0 else CHUNK)

    def read(self, size: int = -1) -> bytes:
        out = bytearray()
        while size < 0 or len(out) < size:
            chunk = self.read1(CHUNK if size < 0 else min(CHUNK, size - len(out)))
            if not chunk:
                break
            out += chunk
        return bytes(out)

    def readline(self, limit: int = -1) -> bytes:
        out = bytearray()
        while limit < 0 or len(out) < limit:
            self._arm()
            ahead = self.buffered.peek(1)  # at most one read of the socket
            if not ahead:
                break
            room = len(ahead) if limit < 0 else min(len(ahead), limit - len(out))
            end = ahead.find(b"\n", 0, room)
            out += self.buffered.read(end + 1 if end >= 0 else room)  # buffered
            if end >= 0:
                break
        return bytes(out)

    def close(self) -> None:
        self.buffered.close()


class Body:
    """The request body: exactly Content-Length bytes, within the request's
    deadline (the Wire's)."""

    def __init__(self, wire: Wire, length: int) -> None:
        self.wire, self.left = wire, length

    def read(self, size: int = -1) -> bytes:
        if self.left <= 0:
            return b""
        want = self.left if size is None or size < 0 else min(size, self.left)
        try:
            data = self.wire.read1(min(want, CHUNK))
        except TimeoutError:
            raise Refusal(408, "timeout", "the request took over its time") from None
        if not data:
            raise Refusal(400, "short_body", "the body is shorter than Content-Length")
        self.left -= len(data)
        return data

    def drain(self) -> None:
        while self.left > 0:
            self.read(CHUNK)


@dataclass
class Site:
    """The site folder and the index of its live units (unit -> manifest entry)."""

    root: Path
    units: dict[str, dict] = field(default_factory=dict)
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    state_lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def www(self) -> Path:
        return self.root / "www"

    @property
    def store(self) -> Path:
        return self.root / "units"

    @property
    def staging(self) -> Path:
        return self.root / "staging"

    def link(self, unit: str) -> Path:
        return self.www / unit

    def target(self, unit: str, uid: str) -> str:
        # Relative, so it resolves the same wherever the site folder is mounted
        return "../" * unit.count("/") + f"../units/{uid}"

    def start(self) -> None:
        """Make the folders, empty staging, index the live units, and remove the
        copies no symlink refers to (an upload a crash cut short)."""
        for d in (self.www / "p", self.www / "t", self.store, self.staging):
            d.mkdir(parents=True, exist_ok=True)
        for entry in self.staging.iterdir():
            _remove(entry)
        live: set[str] = set()
        candidates = [self.www / u for u in TOP_UNITS]
        candidates += sorted((self.www / "p").iterdir())
        candidates += sorted((self.www / "t").iterdir())
        for path in candidates:
            if not path.exists() and not path.is_symlink():
                continue
            unit = path.relative_to(self.www).as_posix()
            uid = os.readlink(path).rsplit("/", 1)[-1] if path.is_symlink() else ""
            meta = self.store / f"{uid}.json"
            if not UNIT.fullmatch(unit) or not uid or not meta.is_file():
                _remove(path)  # not ours, or a unit whose copy is gone
                continue
            entry = json.loads(meta.read_text())
            entry.pop("id", None)
            self.units[unit] = {"id": uid, **entry}
            live.add(uid)
        for entry in self.store.iterdir():
            if entry.name.removesuffix(".json") not in live:
                _remove(entry)
        for entry in self.www.iterdir():  # anything else in www is not ours
            if entry.name not in ("p", "t", *TOP_UNITS):
                _remove(entry)

    def total(self) -> int:
        with self.state_lock:
            return sum(u.get("charged", u["bytes"]) for u in self.units.values())

    def manifest(self, quota: int) -> dict:
        with self.state_lock:
            units = {
                k: {key: v[key] for key in ("digest", "files", "bytes", "at")}
                for k, v in sorted(self.units.items())
            }
        total = sum(u["bytes"] for u in units.values())
        return {"version": 1, "bytes": total, "quota": quota, "units": units}

    def swap(self, unit: str, uid: str, entry: dict) -> None:
        """Move a staged unit live (holding the write lock)."""
        staged = self.staging / uid
        meta = self.staging / f"{uid}.json"
        meta.write_text(json.dumps({"unit": unit, **entry}))
        with open(meta, "rb") as f:
            os.fsync(f.fileno())
        _fsync_dir(self.staging)
        os.rename(staged, self.store / uid)
        os.rename(meta, self.store / f"{uid}.json")
        _fsync_dir(self.store)
        tmp = self.staging / f"{uid}.link"
        os.symlink(self.target(unit, uid), tmp)
        link = self.link(unit)
        os.replace(tmp, link)
        _fsync_dir(link.parent)
        with self.state_lock:
            old = self.units.get(unit)
            self.units[unit] = {"id": uid, **entry}
        if old:
            self._drop_copy(old["id"])

    def delete(self, unit: str) -> bool:
        """Take a unit off the site (holding the write lock). False: it was not on."""
        link = self.link(unit)
        if link.is_symlink() or link.exists():
            _remove(link)
            _fsync_dir(link.parent)
        with self.state_lock:
            old = self.units.pop(unit, None)
        if old:
            self._drop_copy(old["id"])
        return old is not None

    def live(self) -> list[str]:
        with self.state_lock:
            return sorted(self.units)

    def _drop_copy(self, uid: str) -> None:
        _remove(self.store / uid)
        _remove(self.store / f"{uid}.json")


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path, ignore_errors=True)


class _TarInfo(tarfile.TarInfo):
    """A member's header, refusing a pax or GNU long-name block over MAX_META
    before tarfile reads it into memory."""

    def _proc_member(self, tar):
        if self.type in META_TYPES and self.size > MAX_META:
            raise Refusal(400, "bad_tar", "a tar header block is over 64 KiB")
        return super()._proc_member(tar)


def unpack(
    body: Body, dest: Path, config: Config, unit: str, room: int
) -> dict[str, tuple[str, int]]:
    """Unpack the tar in ``body`` into ``dest`` one member at a time: regular
    files only, each path checked against the unit's kind, no duplicates, within
    the limits. Returns path -> (sha256 hex, size). ``room`` is what the quota
    leaves for this unit, counted as charged()."""
    hashes: dict[str, tuple[str, int]] = {}
    total = 0
    dest.mkdir()
    made: set[str] = set()
    try:
        # Streamed, member by member
        tar = tarfile.open(fileobj=body, mode="r|", tarinfo=_TarInfo)
    except tarfile.TarError:
        raise Refusal(400, "bad_tar", "the body is not a tar") from None
    try:
        while True:
            try:
                member = tar.next()
            except tarfile.TarError as error:
                raise Refusal(400, "bad_tar", f"the tar is damaged: {error}") from None
            if member is None:
                break
            name = member.name
            regular = member.type in (tarfile.REGTYPE, tarfile.AREGTYPE)
            if not regular or member.sparse is not None:
                raise Refusal(422, "bad_member", f"{name!r} is not a regular file")
            parts = name.split("/")
            if len(parts) > MAX_DEPTH or not all(SEGMENT.fullmatch(p) for p in parts):
                raise Refusal(422, "bad_member", f"{name!r} is not an allowed path")
            if not member_allowed(unit, parts):
                raise Refusal(422, "bad_member", f"{unit} may not hold {name!r}")
            if name in hashes:
                raise Refusal(422, "bad_member", f"{name!r} is in the tar twice")
            for i in range(1, len(parts)):
                prefix = "/".join(parts[:i])
                if prefix in hashes:
                    raise Refusal(422, "bad_member", f"{name!r} is under a file")
            if name in made:
                raise Refusal(422, "bad_member", f"{name!r} is also a folder")
            if len(hashes) >= config.max_files:
                raise Refusal(413, "too_many_files", f"over {config.max_files} files")
            if member.size > config.max_file:
                raise Refusal(413, "file_too_large", f"{name!r} is over the limit")
            total += charged(member.size)
            if total > room:
                raise Refusal(507, "over_quota", "the site would be over its quota")
            for i in range(1, len(parts)):
                prefix = "/".join(parts[:i])
                if prefix not in made:
                    (dest / prefix).mkdir()
                    made.add(prefix)
            hashes[name] = (_write(tar, member, dest / name), member.size)
        if not hashes:
            raise Refusal(422, "empty_unit", "the tar holds no files")
        body.drain()  # the tar's end padding
    finally:
        tar.close()
    for d in sorted(made, key=lambda p: -p.count("/")):
        _fsync_dir(dest / d)
    _fsync_dir(dest)
    return hashes


def _write(tar: tarfile.TarFile, member: tarfile.TarInfo, path: Path) -> str:
    source = tar.extractfile(member)
    assert source is not None  # a regular file
    digest = hashlib.sha256()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "wb") as out:
        while chunk := source.read(CHUNK):
            digest.update(chunk)
            out.write(chunk)
        out.flush()
        os.fsync(out.fileno())
    return digest.hexdigest()


class Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.1"
    server_version = "scrap-public"
    sys_version = ""

    def setup(self) -> None:
        self.timeout = self.server.config.timeout
        super().setup()
        self.rfile = Wire(self.rfile, self.connection, self.server.config.timeout)

    def handle_one_request(self) -> None:
        # The request's time starts at its first byte; the wait for it is idle time
        try:
            first = self.rfile.wait()
        except (TimeoutError, ConnectionError):
            first = b""
        if not first:
            self.close_connection = True
            return
        self.rfile.start(self.server.config.timeout)
        super().handle_one_request()

    def linger(self) -> None:
        """Close after an early answer: stop sending, then read and discard what
        the client is still sending (bounded), so the answer is not lost to a
        reset."""
        try:
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_WR)
            end, got = time.monotonic() + LINGER_SECONDS, 0
            while got < LINGER_BYTES and (left := end - time.monotonic()) > 0:
                self.connection.settimeout(left)
                data = self.connection.recv(CHUNK)
                if not data:
                    break
                got += len(data)
        except OSError:
            pass

    def carries_body(self) -> bool:
        length = self.headers.get("Content-Length", "0").strip()
        return length not in ("", "0") or "Transfer-Encoding" in self.headers

    # -- plumbing

    def log_message(self, format: str, *args) -> None:
        # The request line and status only: never a header (the token)
        sys.stderr.write(f"receiver: {format % args}\n")

    def reply(self, status: int, payload: dict | None = None, **headers: str) -> None:
        data = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.connection.settimeout(WRITE_TIMEOUT)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def refuse(self, error: Refusal, *, close: bool = False) -> None:
        if close:
            self.close_connection = True
        headers = dict(error.headers)
        if error.status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        if error.status == 503:
            headers["Retry-After"] = "1"
        self.reply(
            error.status, {"error": error.error, "detail": error.detail}, **headers
        )

    def authorised(self) -> bool:
        given = self.headers.get("Authorization", "")
        scheme, _, token = given.partition(" ")
        expected = self.server.config.token.encode()
        ok = scheme.lower() == "bearer" and hmac.compare_digest(
            token.strip().encode("utf-8", "replace"), expected
        )
        return ok

    def length(self, limit: int) -> int:
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            raise Refusal(411, "length_required", "send Content-Length, not chunked")
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise Refusal(411, "length_required", "Content-Length is required")
        if not digits(raw):
            raise Refusal(400, "bad_request", "Content-Length is not a number")
        if int(raw) > limit:
            raise Refusal(413, "body_too_large", f"the body is over {limit} bytes")
        return int(raw)

    def media(self, wanted: str) -> None:
        given = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if given != wanted:
            raise Refusal(415, "unsupported_media_type", f"send {wanted}")

    def route(self) -> tuple[str, str | None]:
        """(route, unit). Everything but /healthz needs the token: 401 first."""
        path = self.path
        if path == "/healthz":
            return "healthz", None
        if not self.authorised():
            raise Refusal(401, "unauthorized", "a valid bearer token is required")
        if path == "/v1/manifest":
            return "manifest", None
        if path == "/v1/sync":
            return "sync", None
        if path.startswith(UNITS_PREFIX):
            unit = path[len(UNITS_PREFIX) :]
            if not UNIT.fullmatch(unit):
                raise Refusal(422, "bad_unit", "not a unit (p/<slug>, t/<key>, …)")
            return "unit", unit
        raise Refusal(404, "not_found", "no such route")

    ALLOWED = {"healthz": "GET, HEAD", "manifest": "GET, HEAD", "sync": "POST",
               "unit": "PUT, DELETE"}  # fmt: skip

    def checked(self) -> tuple[str, str | None]:
        """Route and method checks, and for a body the headers: before any read."""
        name, unit = self.route()
        method = "GET" if self.command == "HEAD" else self.command
        if method not in self.ALLOWED[name]:
            raise Refusal(
                405,
                "method_not_allowed",
                f"{self.command} is not allowed here",
                Allow=self.ALLOWED[name],
            )
        if self.command == "PUT":
            self.media(TAR_TYPES)
            self.length(self.server.config.max_body)
        elif self.command == "POST":
            self.media("application/json")
            self.length(MiB)
        return name, unit

    def handle_expect_100(self) -> bool:
        # Answer a bad upload before the client sends its body
        try:
            self.checked()
        except Refusal as error:
            self.refuse(error, close=True)
            self.linger()
            return False
        return super().handle_expect_100()

    def dispatch(self) -> None:
        try:
            self.answer()
        finally:
            if self.close_connection:
                self.linger()

    def answer(self) -> None:
        try:
            name, unit = self.checked()
        except Refusal as error:
            # The body (if any) was not read: the connection cannot be reused
            self.refuse(error, close=self.carries_body())
            return
        if self.command in ("GET", "HEAD", "DELETE") and self.carries_body():
            self.close_connection = True  # its body is never read
        try:
            getattr(self, f"on_{name}")(unit)
        except Refusal as error:
            self.refuse(error)
        except (ConnectionError, TimeoutError):
            raise
        except OSError as error:
            # A disk full (or another failure writing the site): an answer, not
            # only a traceback. The body may be unread, so close.
            full = error.errno in (errno.ENOSPC, errno.EDQUOT)
            self.log_message("error writing the site: %s", error)
            if full:
                failure = Refusal(507, "over_quota", "the site's disk is full")
            else:
                failure = Refusal(500, "server_error", "the receiver could not write")
            self.refuse(failure, close=True)

    do_GET = do_HEAD = do_PUT = do_DELETE = do_POST = do_PATCH = dispatch  # noqa: N815

    # -- routes

    def on_healthz(self, _unit: None) -> None:
        self.reply(200, {"ok": True})

    def on_manifest(self, _unit: None) -> None:
        self.reply(200, self.server.site.manifest(self.server.config.quota))

    def locked(self):
        if not self.server.site.write_lock.acquire(blocking=False):
            raise Refusal(503, "busy", "another write is in progress; retry")
        return self.server.site.write_lock

    def on_unit(self, unit: str) -> None:
        if self.command == "DELETE":
            lock = self.locked()
            try:
                self.server.site.delete(unit)
            finally:
                lock.release()
            self.reply(204)
            return
        self.put(unit)

    def put(self, unit: str) -> None:
        config, site = self.server.config, self.server.site
        length = self.length(config.max_body)
        claimed = self.headers.get("Scrap-Digest", "").strip().lower()
        try:
            lock = self.locked()
        except Refusal:
            self.close_connection = True
            raise
        body = Body(self.rfile, length)
        uid = secrets.token_hex(8)
        staged = site.staging / uid
        try:
            old = site.units.get(unit)
            room = (
                config.quota
                - site.total()
                + (old.get("charged", old["bytes"]) if old else 0)
            )
            try:
                hashes = unpack(body, staged, config, unit, room)
            except Refusal as error:
                if error.status == 408 or error.error == "short_body":
                    self.close_connection = True
                else:
                    try:
                        body.drain()
                    except Refusal:
                        self.close_connection = True
                raise
            if unit.startswith(NEEDS_INDEX) and "index.html" not in hashes:
                raise Refusal(422, "no_index", f"the {unit} unit needs an index.html")
            digest = unit_digest({path: sha for path, (sha, _) in hashes.items()})
            if not re.fullmatch(r"[0-9a-f]{64}", claimed) or not hmac.compare_digest(
                claimed, digest
            ):
                raise Refusal(400, "digest_mismatch", "Scrap-Digest does not match")
            # bytes: the content's size; charged: what the quota counts (in blocks)
            entry = {
                "digest": digest,
                "files": len(hashes),
                "bytes": sum(size for _, size in hashes.values()),
                "charged": sum(charged(size) for _, size in hashes.values()),
                "at": now(),
            }
            site.swap(unit, uid, entry)
        finally:
            _remove(staged)
            lock.release()
        self.reply(
            200, {"unit": unit, **{k: v for k, v in entry.items() if k != "charged"}}
        )

    def on_sync(self, _unit: None) -> None:
        length = self.length(MiB)
        body = Body(self.rfile, length)
        raw = b""
        while chunk := body.read(CHUNK):
            raw += chunk
        try:
            keep = json.loads(raw)["keep"]
        except (ValueError, KeyError, TypeError):
            raise Refusal(400, "bad_request", 'send {"keep": [unit, ...]}') from None
        if not isinstance(keep, list) or not all(isinstance(u, str) for u in keep):
            raise Refusal(400, "bad_request", "keep is a list of units")
        if not keep:
            raise Refusal(422, "empty_keep", "refusing to delete every unit")
        if "home" not in keep:
            raise Refusal(422, "no_home", "keep must list home")
        bad = [u for u in keep if not UNIT.fullmatch(u)]
        if bad:
            raise Refusal(422, "bad_unit", f"not units: {bad[:5]}")
        lock = self.locked()
        try:
            wanted = set(keep)
            deleted = [u for u in self.server.site.live() if u not in wanted]
            for unit in deleted:
                self.server.site.delete(unit)
        finally:
            lock.release()
        self.reply(200, {"deleted": deleted})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, config: Config) -> None:
        self.config = config
        self.site = Site(config.site)
        self.site.start()
        super().__init__((config.host, config.port), Handler)


def main() -> None:
    config = config_from_env(dict(os.environ))
    server = Server(config)
    host, port = server.server_address[:2]
    sys.stderr.write(f"receiver: listening on {host}:{port}, site {config.site}\n")

    def stop(signum: int, _frame) -> None:
        sys.stderr.write(f"receiver: {signal.Signals(signum).name}, stopping\n")
        # shutdown() waits for serve_forever, so not from its own thread
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        # Let a write in progress finish (it is atomic either way: an unfinished
        # one leaves only staging, which the next start empties)
        if server.site.write_lock.acquire(timeout=config.timeout):
            server.site.write_lock.release()
        server.server_close()


if __name__ == "__main__":
    main()
