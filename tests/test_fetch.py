"""Fetching a link for enrich: public addresses only, limits, readable text."""

import gzip
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from scrap import fetch
from scrap.fetch import FetchError


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.1.2.3", "192.168.1.1", "172.16.0.1", "169.254.169.254",
     "100.76.74.70", "0.0.0.0", "::1", "fe80::1", "fd00::1", "::ffff:127.0.0.1",
     "224.0.0.1", "fd7a:115c:a1e0::1"],
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
        status, headers, body = self.routes[self.path]
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
    server = HTTPServer(("127.0.0.1", 0), Site)
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
