"""Fetch a web page for enrichment: safely, and only its readable text.

The page is untrusted. Only http(s) on ports 80 and 443; every address the host
resolves to must be public (no private, loopback, link-local, CGNAT/tailnet, multicast,
reserved or metadata address), checked again at every redirect, and the connection is
made to the address that was checked (a second DNS answer cannot swap it). At most
MAX_BYTES are read and the whole fetch, redirects included, gives up after DEADLINE
seconds. No cookies, no credentials, no proxy. Only HTML and plain text are read.
"""

import http.client
import ipaddress
import os
import re
import socket
import ssl
import threading
import time
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit

__all__ = ["FetchError", "Fetched", "fetch", "readable", "check_url"]

MAX_BYTES = 2_000_000  # of the body, after decompression
MAX_REDIRECTS = 5
DEADLINE = 20.0  # seconds, the whole fetch
MAX_TEXT = 20_000  # characters of readable text kept
PORTS = {"http": 80, "https": 443}
AGENT = "scrap/1 (personal notes; fetches a page its owner saved)"
TYPES = ("text/html", "application/xhtml+xml", "text/plain")
# is_global yet not to be fetched: IPv4-compatible (::/96), NAT64 (a translator
# reaches any IPv4 address) and the old site-local IPv6 range
DENY = [ipaddress.ip_network(n) for n in ("::/96", "64:ff9b::/96", "fec0::/10")]
SAFE = "/%:@!$&'()*+,;=~"  # left as they are in a path: %XX is kept, not quoted twice


class FetchError(Exception):
    """A page that could not, or must not, be fetched (the reason, for the user)."""


@dataclass
class Fetched:
    url: str  # where it ended up, after redirects
    title: str
    description: str
    text: str  # readable text, at most MAX_TEXT characters


def public(ip: str) -> bool:
    """Whether an address is one the open internet routes to (an IPv4-mapped IPv6
    address is judged as its IPv4 one)."""
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if any(addr in net for net in DENY):
        return False
    return addr.is_global and not addr.is_multicast


def check_url(url: str) -> tuple[str, str, int]:
    """(scheme, host, port) of a URL scrap may fetch; FetchError if not."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise FetchError("not a valid address") from None
    if parts.scheme not in PORTS or not parts.hostname:
        raise FetchError("only http and https pages are fetched")
    if parts.username or parts.password:
        raise FetchError("an address with a login in it is not fetched")
    port = port or PORTS[parts.scheme]
    if port != PORTS[parts.scheme]:
        raise FetchError("only the standard ports are fetched")
    try:  # an international name as DNS and the certificate have it
        host = parts.hostname.encode("idna").decode("ascii")
    except UnicodeError:
        raise FetchError("not a valid address") from None
    return parts.scheme, host, port


def target(url: str) -> str:
    """A URL's path and query as sent: anything not ASCII percent-encoded (UTF-8),
    %XX already there kept."""
    parts = urlsplit(url)
    path = quote(parts.path or "/", safe=SAFE)
    return path + (f"?{quote(parts.query, safe=SAFE + '?')}" if parts.query else "")


def resolve(host: str, port: int, getaddrinfo=socket.getaddrinfo) -> str:
    """One address for host, after checking that every address it has is public."""
    try:
        infos = getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise FetchError("the site's name does not resolve") from None
    ips = [info[4][0] for info in infos]
    if not ips:
        raise FetchError("the site's name does not resolve")
    if not all(public(ip) for ip in ips):
        raise FetchError("the address is private or local: not fetched")
    return ips[0]


class _Pinned(http.client.HTTPSConnection):
    """HTTPS to an address checked already, with the certificate checked for host."""

    def __init__(self, host: str, ip: str, port: int, timeout: float):
        context = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.fd = os.dup(sock.fileno())  # the deadline's own (handshake too)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


class _PinnedHttp(http.client.HTTPConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.fd = os.dup(self.sock.fileno())  # the deadline's own


class _Deadline:
    """Cuts a connection's socket at the deadline, wherever it is blocked (connect,
    TLS handshake, headers or body), so a site dripping bytes cannot hold it. It
    shuts down through conn.fd, the connection's own duplicate of the socket's fd,
    which only close() closes: http.client may close the socket first (at the end
    of a Connection: close body), and the timer must never touch an fd number that
    something else has been given since."""

    def __init__(self, conn: http.client.HTTPConnection, left: float):
        self.conn, self.lock, self.done = conn, threading.Lock(), False
        self.timer = threading.Timer(max(left, 0.0), self.cut)
        self.timer.daemon = True
        self.timer.start()

    def cut(self) -> None:
        with self.lock:
            fd = getattr(self.conn, "fd", None)
            if self.done or fd is None:
                return
            try:  # shutdown reaches the socket however many fds it has
                with socket.socket(fileno=os.dup(fd)) as sock:
                    sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self) -> None:
        """Once the fetch is over: the timer stopped, the duplicate fd closed."""
        self.timer.cancel()
        with self.lock:
            self.done = True
            fd, self.conn.fd = getattr(self.conn, "fd", None), None  # type: ignore[attr-defined]
            if fd is not None:
                os.close(fd)


def _limit(conn: http.client.HTTPConnection, until: float) -> None:
    """FetchError if the deadline has passed; else the socket's timeout for its next
    read, what is left at most 10 s, while the connection still holds the socket (it
    gives it to the response of a Connection: close answer: _Deadline guards that)."""
    left = until - time.monotonic()
    if left <= 0:
        raise FetchError("the site took too long")
    if conn.sock is not None:
        conn.sock.settimeout(min(10.0, left))


def _read(
    response: http.client.HTTPResponse, conn: http.client.HTTPConnection, until: float
) -> bytes:
    """The body, decompressed, at most MAX_BYTES; FetchError past it or the deadline
    (checked between reads from the socket: read1 never waits for more)."""
    coding = (response.getheader("Content-Encoding") or "identity").lower()
    if coding not in ("identity", "gzip", "deflate"):
        raise FetchError(f"the page is encoded as {coding[:20]}")
    inflate = None
    if coding != "identity":
        inflate = zlib.decompressobj(zlib.MAX_WBITS | 32)  # gzip or zlib header
    out = bytearray()
    while True:
        _limit(conn, until)
        chunk = response.read1(64 * 1024)
        if time.monotonic() > until:  # cut at the deadline: not the end of the page
            raise FetchError("the site took too long")
        if not chunk:
            return bytes(out)
        if inflate is not None:
            try:
                chunk = inflate.decompress(chunk, MAX_BYTES + 1 - len(out))
            except zlib.error:
                raise FetchError("the page could not be decompressed") from None
        out += chunk
        if len(out) > MAX_BYTES:
            raise FetchError("the page is too large")


def get(url: str, getaddrinfo=socket.getaddrinfo) -> tuple[str, str, bytes]:
    """(final URL, content type, body) of a GET, following redirects, each checked."""
    until = time.monotonic() + DEADLINE
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port = check_url(url)
        ip = resolve(host, port, getaddrinfo)
        left = until - time.monotonic()
        if left <= 0:
            raise FetchError("the site took too long")
        kind = _Pinned if scheme == "https" else _PinnedHttp
        conn = kind(host, ip, port, timeout=min(left, 10.0))
        deadline = _Deadline(conn, left)
        try:
            conn.request(
                "GET",
                target(url),
                headers={
                    "User-Agent": AGENT,
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                    "Accept-Language": "en",
                },
            )
            _limit(conn, until)
            response = conn.getresponse()
            _limit(conn, until)  # headers cut short at the deadline are not the page's
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise FetchError("a redirect with nowhere to go")
                url = urljoin(url, location.strip())
                continue
            if response.status != 200:
                raise FetchError(f"the site answered {response.status}")
            mime = (response.getheader("Content-Type") or "").lower()
            if mime.split(";")[0].strip() not in TYPES:
                raise FetchError("not a web page (no readable text)")
            return url, mime, _read(response, conn, until)
        except (OSError, http.client.HTTPException) as error:
            late = time.monotonic() > until  # cut at the deadline
            if late or isinstance(error, TimeoutError | socket.timeout):
                raise FetchError("the site took too long") from None
            why = type(error).__name__
            raise FetchError(f"could not fetch the page ({why})") from None
        finally:
            deadline.close()
            conn.close()
    raise FetchError("too many redirects")


CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([\w-]{1,40})""", re.I)


def decode(body: bytes, mime: str) -> str:
    charset = None
    if "charset=" in mime:
        charset = mime.split("charset=")[-1].split(";")[0].strip().strip('"')
    elif m := CHARSET.search(body[:4096]):
        charset = m[1].decode("ascii")
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


SKIP = {
    "script", "style", "noscript", "svg", "template", "iframe", "nav", "header",
    "footer", "aside", "form", "button", "select", "canvas", "head",
}  # fmt: skip
BLOCK = {
    "p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section",
    "article", "main", "blockquote", "pre", "dd", "dt", "figcaption", "td",
}  # fmt: skip
VOID = {"br", "img", "meta", "link", "input", "hr", "source", "wbr", "area", "base"}


class _Text(HTMLParser):
    """The title, description and readable text of an HTML page: what is in its
    <article> (else <main>, else <body>), without scripts, menus and the like."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0  # depth inside a skipped element
        self.in_title = False
        self.title, self.meta = "", {}
        self.parts: dict[str, list[str]] = {"article": [], "main": [], "body": []}
        self.open = {"article": 0, "main": 0}

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:title", "description", "og:description", "twitter:title"):
                self.meta.setdefault(key, a.get("content", ""))
            return
        if tag in VOID:
            if tag == "br":
                self._add("\n")
            return
        if tag == "title":
            self.in_title = True
        if tag in SKIP and tag != "head":
            self.skip += 1
        if tag in self.open:
            self.open[tag] += 1
        if tag in BLOCK:
            self._add("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag in SKIP and tag != "head" and self.skip:
            self.skip -= 1
        if tag in self.open and self.open[tag]:
            self.open[tag] -= 1
        if tag in BLOCK:
            self._add("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
            return
        if not self.skip:
            self._add(data)

    def _add(self, text: str) -> None:
        self.parts["body"].append(text)
        for tag, depth in self.open.items():
            if depth:
                self.parts[tag].append(text)


def tidy(text: str) -> str:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def readable(body: bytes, mime: str) -> tuple[str, str, str]:
    """(title, description, text) of a page's bytes."""
    text = decode(body, mime)
    if mime.startswith("text/plain"):
        return "", "", tidy(text)[:MAX_TEXT]
    parser = _Text()
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # noqa: BLE001  broken HTML: what was read so far
        pass
    meta = parser.meta
    title = tidy(meta.get("og:title") or parser.title or meta.get("twitter:title", ""))
    about = tidy(meta.get("og:description") or meta.get("description", ""))
    for part in ("article", "main", "body"):
        found = tidy("".join(parser.parts[part]))
        if len(found) > 200 or part == "body":
            break
    return title[:300], about[:1000], found[:MAX_TEXT]


def fetch(url: str, getaddrinfo=socket.getaddrinfo) -> Fetched:
    """A page's readable text; FetchError (with a reason fit to show) if it can't."""
    final, mime, body = get(url, getaddrinfo)
    title, about, text = readable(body, mime)
    return Fetched(final, title, about, text)
