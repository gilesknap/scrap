"""Host and Origin checks for the web app (everything but /mcp), #238.

The same allow-list as /mcp's (`mcp_server.security()`: loopback and the hosts of
$SCRAP_PUBLIC_URL), so one setting covers both. Two attacks are closed:

- DNS rebinding: a page on an attacker's name that now resolves to scrap sends
  `Host: <that name>`. A Host that is not allowed gets 421, whatever the method.
- Cross-site writes (a form auto-submitted from another site, a `fetch` with
  `no-cors`): browsers always send `Origin` on a cross-origin POST, PUT, PATCH or
  DELETE. A present Origin that is not allowed (`null` included) gets 403, as does a
  write the browser marks `Sec-Fetch-Site: cross-site`. The one exception: `null` on
  /share with `Sec-Fetch-Site: none` or `same-origin` (an Android share sheet opening
  the installed app, if its service worker did not take the POST; sw.ts normally does).

Not checked: a request with no Origin (curl, the CLI, hooks, tests; a browser does
not leave it off a cross-origin write), and GET, HEAD and OPTIONS Origins (they change
nothing, and without CORS headers a page cannot read the reply). `X-Forwarded-Host` is
ignored: only the Host scrap is sent counts, as for /mcp.
"""

import ipaddress
import logging
from urllib.parse import urlsplit

from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

__all__ = ["HostOrigin"]

log = logging.getLogger(__name__)
SAFE = ("GET", "HEAD", "OPTIONS")
DEFAULT_PORT = {"http": "80", "https": "443"}
EXEMPT = ("/mcp", "/healthz")  # /mcp has its own check; probes come by any name
# (/mcp/... downloads, mcp_files, are GETs checked here like any other route)


def split(netloc: str) -> tuple[str, str] | None:
    """(host, port) of a Host header or URL netloc, lower case, no trailing dot;
    port "" if none. None if it is not one."""
    netloc = netloc.strip().lower()
    if netloc.startswith("["):  # [::1]:8000
        host, bracket, rest = netloc[1:].partition("]")
        if not bracket or (rest and not rest.startswith(":")):
            return None
        host, port = f"[{host}]", rest[1:]
    else:
        host, _, port = netloc.rpartition(":") if ":" in netloc else (netloc, "", "")
    host = host.rstrip(".")
    if not host or (port and not port.isdigit()) or "/" in host or "@" in host:
        return None
    return host, port


def is_ip(host: str) -> bool:
    """An IP address as a Host: it names no attacker's DNS record, so cannot be
    rebinding (a cross-site write from an IP-address page is stopped by Origin)."""
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


class HostOrigin:
    """ASGI middleware: 421 for a Host not allowed, 403 for a state-changing request
    whose Origin is not (see the module docstring). /mcp and /healthz are left to
    their own checks."""

    def __init__(self, app: ASGIApp, settings: TransportSecuritySettings) -> None:
        self.app = app
        self.exact: set[tuple[str, str]] = set()  # host, port as written
        self.any_port: set[str] = set()  # "host:*"
        for name in settings.allowed_hosts:
            if name.endswith(":*"):
                self.any_port.add(name[:-2].lower().rstrip("."))
            elif (got := split(name)) is not None:
                self.exact.add(got)
        self.origins = {o.lower().rstrip("/") for o in settings.allowed_origins}

    def host_ok(self, host: str, port: str) -> bool:
        return is_ip(host) or host in self.any_port or (host, port) in self.exact

    def origin_ok(self, origin: str, host: str, port: str) -> bool:
        """Listed (a trailing `:*` is any port), or the page's own IP address (an
        install with no SCRAP_PUBLIC_URL, reached by address): the Origin's host and
        port are the Host's. A name must be listed, scheme and all."""
        parts = urlsplit(origin)
        got = split(parts.netloc)
        if parts.scheme not in DEFAULT_PORT or got is None:
            return False
        if parts.path or parts.query or parts.fragment or "?" in origin:
            return False
        site = f"{parts.scheme}://{got[0]}"
        if f"{site}:{got[1]}" in self.origins or (
            got[1] and f"{site}:*" in self.origins
        ):
            return True
        if not got[1] and site in self.origins:
            return True
        default = DEFAULT_PORT[parts.scheme]
        return (
            is_ip(host) and got[0] == host and (got[1] or default) == (port or default)
        )

    @staticmethod
    def cross_site(scope: Scope, origins: list[bytes], path: str) -> bool:
        """A browser says (Sec-Fetch-Site, which a page cannot set) the write is from
        another site: refused whatever Origin it carries. `Origin: null` is accepted on
        /share only when the browser says it is the user's own action (`none`: the
        Android share sheet starting the installed app) or same-origin."""
        site = b""
        for k, v in scope["headers"]:
            if k == b"sec-fetch-site":
                site = v.strip().lower()
        if site == b"cross-site":
            return True
        null = [o.strip().lower() == b"null" for o in origins]
        return any(null) and not (
            path == "/share" and len(origins) == 1 and site in (b"none", b"same-origin")
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if (root := scope.get("root_path", "")) and path.startswith(root):
            path = path[len(root) :]  # as BearerAuth does
        if scope["type"] != "http" or path in EXEMPT:
            await self.app(scope, receive, send)
            return
        hosts = [v for k, v in scope["headers"] if k == b"host"]
        origins = [v for k, v in scope["headers"] if k == b"origin"]
        got = split(hosts[0].decode("latin-1")) if len(hosts) == 1 else None
        refusal = None
        if got is None or not self.host_ok(*got):
            log.warning("Refused Host %r on %s", hosts, path)
            refusal = PlainTextResponse(
                "Invalid Host header (add its address to SCRAP_PUBLIC_URL)", 421
            )
        elif scope["method"] not in SAFE and self.cross_site(scope, origins, path):
            log.warning("Refused cross-site write %s %s", scope["method"], path)
            refusal = PlainTextResponse("Invalid Origin header", 403)
        elif origins and scope["method"] not in SAFE:
            origin = origins[0].decode("latin-1").strip().lower()
            if origin != "null" and (
                len(origins) > 1 or not self.origin_ok(origin, *got)
            ):  # a lone `null` was settled by cross_site
                log.warning(
                    "Refused Origin %r on %s %s", origins, scope["method"], path
                )
                refusal = PlainTextResponse("Invalid Origin header", 403)
        if refusal:
            await refusal(scope, receive, send)
            return
        await self.app(scope, receive, send)
