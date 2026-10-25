"""Fetching a link for enrich: public addresses only, limits, readable text."""

import gzip
import os
import socket
import ssl
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scrap import fetch
from scrap.fetch import FetchError


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.1.2.3", "192.168.1.1", "172.16.0.1", "169.254.169.254",
     "100.100.1.1", "0.0.0.0", "::1", "fe80::1", "fd00::1", "::ffff:127.0.0.1",
     "224.0.0.1", "fd7a:115c:a1e0::1", "::7f00:1", "64:ff9b::7f00:1", "fec0::1",
     "64:ff9b::808:808"],
)  # fmt: skip
def test_private_local_tailnet_and_metadata_addresses_are_not_public(ip):
    assert not fetch.public(ip)


@pytest.mark.parametrize("ip", ["93.184.216.34", "2606:2800:220:1::1"])
def test_public_addresses_are(ip):
    assert fetch.public(ip)


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/", "file:///etc/passwd", "https://u:p@example.com/",
     "http://example.com:8080/", "https:///nohost", "javascript:alert(1)"],
)  # fmt: skip
def test_other_schemes_ports_and_logins_are_refused(url):
    with pytest.raises(FetchError):
        fetch.check_url(url)


def answers(*ips):
    def getaddrinfo(host, port, type=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    return getaddrinfo


def test_a_name_with_any_private_address_is_refused():
    with pytest.raises(FetchError, match="private"):
        fetch.resolve("example.com", 443, answers("93.184.216.34", "10.0.0.1"))
    ip = "93.184.216.34"
    assert fetch.resolve("example.com", 443, answers(ip)) == ip


class Site(BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):
        route = self.routes[self.path]
        if callable(route):
            return route(self)
        status, headers, body = route
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002  quiet
        pass


@pytest.fixture
def site(monkeypatch):
    """A local server standing in for good.example (127.0.0.1 counted as public for
    it only), on its own port (counted as the standard one)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    server.daemon_threads = True  # a dripping handler is not waited for
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(fetch, "PORTS", {"http": port, "https": 443})
    real = fetch.public
    monkeypatch.setattr(fetch, "public", lambda ip: ip == "127.0.0.1" or real(ip))
    names = {"good.example": "127.0.0.1", "meta.example": "169.254.169.254"}

    def getaddrinfo(host, p, type=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (names[host], p))]

    yield f"http://good.example:{port}", getaddrinfo
    server.shutdown()
    server.server_close()


HTML = (
    b"""<html><head><title>Ignored</title>
<meta property="og:title" content="The Real Title">
<meta name="description" content="What it is about">
<script>var steal = 1;</script><style>p {}</style></head>
<body><nav>Home | About</nav><header>Site name</header>
<article><h1>Heading</h1><p>First paragraph of the article, long enough to count.</p>
<p>Second paragraph &amp; more.</p>"""
    + b"<p>filler text here.</p>" * 20
    + b"""
</article><footer>Copyright</footer></body></html>"""
)


def test_a_page_is_fetched_and_reduced_to_its_readable_text(site):
    base, dns = site
    Site.routes = {"/a": (200, {"Content-Type": "text/html; charset=utf-8"}, HTML)}
    got = fetch.fetch(base + "/a", dns)
    assert got.title == "The Real Title"
    assert got.description == "What it is about"
    assert "First paragraph" in got.text and "Second paragraph & more." in got.text
    for junk in ("steal", "Home | About", "Site name", "Copyright", "Ignored"):
        assert junk not in got.text


def test_gzip_is_read_and_redirects_are_followed(site):
    base, dns = site
    Site.routes = {
        "/old": (301, {"Location": "/new"}, b""),
        "/new": (200, {"Content-Type": "text/plain", "Content-Encoding": "gzip"},
                 gzip.compress(b"plain words")),
    }  # fmt: skip
    got = fetch.fetch(base + "/old", dns)
    assert got.url == base + "/new" and got.text == "plain words"


def test_a_redirect_to_a_metadata_address_is_refused(site):
    base, dns = site
    port = base.rsplit(":", 1)[1]
    Site.routes = {"/r": (302, {"Location": f"http://meta.example:{port}/x"}, b"")}
    with pytest.raises(FetchError, match="private"):
        fetch.fetch(base + "/r", dns)


def test_size_type_status_and_redirect_limits(site, monkeypatch):
    base, dns = site
    monkeypatch.setattr(fetch, "MAX_BYTES", 1000)
    Site.routes = {
        "/big": (200, {"Content-Type": "text/html"}, b"x" * 5000),
        "/bomb": (200, {"Content-Type": "text/html", "Content-Encoding": "gzip"},
                  gzip.compress(b"x" * 100_000)),
        "/pdf": (200, {"Content-Type": "application/pdf"}, b"%PDF"),
        "/gone": (404, {"Content-Type": "text/html"}, b"no"),
        "/loop": (302, {"Location": "/loop"}, b""),
    }  # fmt: skip
    for path, why in [("/big", "too large"), ("/bomb", "too large"),
                      ("/pdf", "not a web page"), ("/gone", "404"),
                      ("/loop", "too many redirects")]:  # fmt: skip
        with pytest.raises(FetchError, match=why):
            fetch.fetch(base + path, dns)


def drip(head: bool):
    """A handler sending a byte every 0.1 s for 5 s: in the headers, or the body."""

    def handler(self):
        self.wfile.write(b"HTTP/1.0 200 OK\r\n")
        if not head:
            self.wfile.write(b"Content-Type: text/plain\r\n\r\n")
        try:
            for _ in range(50):
                self.wfile.write(b"X-A: b\r\n" if head else b"x")
                self.wfile.flush()
                time.sleep(0.1)
        except OSError:
            pass

    return handler


@pytest.mark.timing  # run alone: see conftest.py
@pytest.mark.parametrize("head", [False, True])
def test_a_site_dripping_bytes_is_cut_at_the_deadline(site, monkeypatch, head):
    base, dns = site
    monkeypatch.setattr(fetch, "DEADLINE", 0.5)
    Site.routes = {"/drip": drip(head)}
    start = time.monotonic()
    with pytest.raises(FetchError, match="too long"):
        fetch.fetch(base + "/drip", dns)
    assert time.monotonic() - start < 3  # cut near 0.5 s: the drip goes on far longer


def test_a_page_that_does_not_decompress_is_refused(site):
    base, dns = site
    raw = zlib.compressobj(wbits=-15)  # raw deflate, which some servers send
    body = raw.compress(b"words") + raw.flush()
    Site.routes = {
        "/raw": (200, {"Content-Type": "text/plain", "Content-Encoding": "deflate"},
                 body),
        "/bad": (200, {"Content-Type": "text/plain", "Content-Encoding": "gzip"},
                 b"\x1f\x8b" + b"junk" * 10),
    }  # fmt: skip
    for path in ("/raw", "/bad"):
        with pytest.raises(FetchError, match="decompressed"):
            fetch.fetch(base + path, dns)


def test_a_url_that_is_not_ascii_is_sent_encoded(site):
    base, dns = site
    seen = []

    def page(self):
        seen.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    Site.routes = {"/wiki/Caf%C3%A9?q=th%C3%A9%20vert&a=%2F": page}
    got = fetch.fetch(base + "/wiki/Café?q=thé%20vert&a=%2F", dns)
    assert got.text == "ok" and seen == ["/wiki/Caf%C3%A9?q=th%C3%A9%20vert&a=%2F"]
    assert fetch.target("http://x/a%20b/c d") == "/a%20b/c%20d"  # %XX kept


def test_an_international_name_is_looked_up_and_sent_as_idna():
    assert fetch.check_url("https://bücher.example/x")[1] == "xn--bcher-kva.example"


def test_https_connects_to_the_checked_address_and_verifies_the_name(monkeypatch):
    calls = {}

    def create_connection(address, timeout):
        calls["address"] = address
        return socket.socket()

    def wrap_socket(sock, server_hostname):
        calls["server_hostname"] = server_hostname
        sock.close()
        return sock

    monkeypatch.setattr(fetch.socket, "create_connection", create_connection)
    conn = fetch._Pinned("good.example", "93.184.216.34", 443, timeout=5)
    context: ssl.SSLContext = conn._context  # pyright: ignore[reportAttributeAccessIssue]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    monkeypatch.setattr(context, "wrap_socket", wrap_socket)
    conn.connect()
    os.close(conn.fd)
    assert calls == {"address": ("93.184.216.34", 443),
                     "server_hostname": "good.example"}  # fmt: skip


def test_the_deadline_never_touches_an_fd_number_given_out_again():
    """http.client may close the socket (end of a Connection: close body) before the
    fetch is over: a late cut must not shut down whatever gets that fd number next."""
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
        conn = fetch._PinnedHttp("good.example", "127.0.0.1", port, timeout=5)
        deadline = fetch._Deadline(conn, 60)
        conn.connect()
        peer, _ = server.accept()
        number = conn.sock.fileno()
        conn.sock.close()  # as http.client does
        a, b = socket.socketpair()
        try:
            assert number in (a.fileno(), b.fileno())  # the number is reused
            deadline.cut()  # the timer firing late
            a.sendall(b"still open")
            assert b.recv(20) == b"still open"
        finally:
            deadline.close()
            for s in (a, b, peer):
                s.close()
        assert conn.fd is None
