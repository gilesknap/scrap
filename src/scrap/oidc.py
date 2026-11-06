"""The login proxy's Keycloak token, checked by scrap itself (ADR 45).

Behind the DLS login (oauth2-proxy through ingress-nginx's external auth) the Ingress
is not the only way in: any pod in the cluster can call scrap's Service, and could
send a forged `X-Auth-Request-Email`. So with `$SCRAP_OIDC_ISSUER` set, every request
but /healthz (probes) and /mcp (its own bearer token, ADR 23) needs a Keycloak access
token in `X-Auth-Request-Access-Token` (nginx sets it from oauth2-proxy's answer,
over any copy the client sent) that:

- is signed by one of the issuer's keys (its discovery document's `jwks_uri`), with
  RS256 or ES256, the algorithm the key is for (never `none` or a shared secret);
- is an access token (`typ` Bearer, as Keycloak's are; not an ID token);
- has `iss` the issuer exactly, and was issued to our client (`azp` is
  `$SCRAP_OIDC_CLIENT_ID`, or it is in `aud`);
- is in date (`exp`, `nbf`, `iat`, with 30 s of leeway for clock skew);
- carries a `preferred_username` (the Keycloak username: at DLS the fedid, which also
  names the user's namespace) in `$SCRAP_ALLOWED_USERS` (comma separated; compared
  lower-cased). Not the email: DLS's Keycloak does not verify emails
  (`email_verified` is false for staff), so it is not the gate.

Otherwise 401 (JSON under /api, else plain text; no redirect, the Ingress does the
login), or 503 when the keys cannot be fetched: never let through on an error. The
checked username is the author of a change (uploads.author). Unset: nothing changes.

Fetches use the standard library (http(s) only, no redirects, a timeout), with
scrap's own cache and back-off (Verifier) rather than PyJWKClient's, whose cooldown
starts only after a fetch that worked. Below app and uploads.
"""

import json
import logging
import os
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import anyio
import jwt
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

__all__ = ["USER", "OidcGate", "Settings", "Verifier", "enabled", "settings"]

log = logging.getLogger(__name__)

HEADER = b"x-auth-request-access-token"
USER = "scrap.oidc_user"  # the scope key the checked username is kept under
ALGORITHMS = ("RS256", "ES256")
LEEWAY = 30  # seconds of clock skew allowed on exp, nbf and iat
TIMEOUT = 5  # seconds for each socket operation of a fetch from the issuer
DEADLINE = 10  # seconds for a whole fetch's body to arrive, from its start
MAX_BYTES = 2**20  # the most a discovery document or key set may be
KEYS_LIFESPAN = 3600  # how long a fetched key set is used before it is fetched again
COOLDOWN = 30  # the least time between refetches for a key id not in the set
RETRY = 10  # seconds after a failed fetch before trying again (503 meanwhile)
LOOPBACK = ("localhost", "127.0.0.1", "::1")


class InvalidTokenError(Exception):
    """No token, or one that is not good for this scrap: 401."""


class KeysUnavailableError(Exception):
    """The issuer's keys cannot be fetched: 503."""


@dataclass(frozen=True)
class Settings:
    issuer: str
    client_id: str
    allowed: frozenset[str]


def enabled() -> bool:
    """Whether the token check is on: $SCRAP_OIDC_ISSUER is set (blank is unset)."""
    return bool(os.environ.get("SCRAP_OIDC_ISSUER", "").strip())


def settings(mcp_guarded: bool) -> Settings | None:
    """The check's settings, or None when $SCRAP_OIDC_ISSUER is unset. An issuer
    without a client id or an allow-list, or one that is not https (but on loopback),
    stops scrap starting: a check that let everyone in would be worse than no start.
    So does one without /mcp's bearer token (mcp_guarded false): /mcp is exempt here,
    so it would be open to anyone who can reach scrap."""
    if not enabled():
        return None
    issuer = os.environ["SCRAP_OIDC_ISSUER"].strip()
    client_id = os.environ.get("SCRAP_OIDC_CLIENT_ID", "").strip()
    raw = os.environ.get("SCRAP_ALLOWED_USERS", "")
    allowed = frozenset(e.strip().lower() for e in raw.split(",") if e.strip())
    if not secure(issuer):
        raise SystemExit(f"SCRAP_OIDC_ISSUER must be an https URL, not {issuer!r}")
    if not client_id:
        raise SystemExit("SCRAP_OIDC_ISSUER is set but SCRAP_OIDC_CLIENT_ID is empty")
    if not allowed:
        raise SystemExit("SCRAP_OIDC_ISSUER is set but SCRAP_ALLOWED_USERS is empty")
    if not mcp_guarded:
        raise SystemExit(
            "SCRAP_OIDC_ISSUER is set but /mcp has no bearer token: set SCRAP_MCP_TOKEN"
            " or SCRAP_MCP_TOKEN_FILE, or /mcp is open to anyone who can reach scrap"
        )
    return Settings(issuer, client_id, allowed)


def secure(url: str) -> bool:
    """https, or http on loopback (a local issuer for testing)."""
    parts = urlsplit(url)
    return parts.scheme == "https" or (
        parts.scheme == "http" and parts.hostname in LOOPBACK
    )


def fetch_json(url: str) -> Any:
    """GET url's JSON: http(s) only, no redirects. Each socket operation has TIMEOUT;
    the body is read a piece at a time and given up past DEADLINE from the start, or
    past MAX_BYTES (KeysUnavailableError), so a slow or huge answer cannot hold a
    fetch for long. (urllib's timeout is per operation: the request and headers are
    bounded only by it, but a fetch holds no lock and blocks no other request.)"""
    if urlsplit(url).scheme not in ("http", "https"):
        raise KeysUnavailableError(f"not an http(s) URL: {url!r}")
    deadline = time.monotonic() + DEADLINE

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None

    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            body = bytearray()
            while piece := response.read1(65536):
                body += piece
                if len(body) > MAX_BYTES:
                    raise KeysUnavailableError(f"{url} is over {MAX_BYTES} bytes")
                if time.monotonic() > deadline:
                    raise KeysUnavailableError(f"{url} took over {DEADLINE} s")
        return json.loads(body)
    except (OSError, ValueError) as error:  # URLError, timeouts, bad JSON
        raise KeysUnavailableError(f"cannot fetch {url}: {error}") from error


class Verifier:
    """Checks a token against Settings. The issuer's keys are found on first use (so
    a Keycloak outage at start is a 503, not a crash loop) and refreshed after
    KEYS_LIFESPAN. While a refresh is in flight the old set still answers; a refresh
    that fails drops an expired set (503 until a fetch works), since a key Keycloak
    has removed may have been removed for a reason.

    scrap's own back-off bounds the fetches, whatever tokens arrive: one fetch at a
    time, never holding the lock (a request meanwhile that the cached keys cannot
    answer gets 503 at once); after a failed fetch, none for RETRY seconds (503); and
    a key id not in the set refetches it at most once per COOLDOWN (401 meanwhile)."""

    def __init__(self, conf: Settings) -> None:
        self.conf = conf
        self.lock = threading.Lock()  # held only to read or change the state below
        self.clock = time.monotonic  # (a test's own clock)
        self.jwks_uri: str | None = None
        self.keys: dict[str, jwt.PyJWK] | None = None
        self.fetching = False
        self.fetched_at = -float("inf")  # the last fetch of the key set that worked
        self.tried_at = -float("inf")  # the last fetch begun
        self.failed_at = -float("inf")  # the last fetch that failed

    def discover(self, known: str | None) -> str:
        """The issuer's jwks_uri (known, else from its discovery document, whose own
        `issuer` must be ours)."""
        if known is not None:
            return known
        found = fetch_json(
            self.conf.issuer.rstrip("/") + "/.well-known/openid-configuration"
        )
        if not isinstance(found, dict) or found.get("issuer") != self.conf.issuer:
            raise KeysUnavailableError("the discovery document is for another issuer")
        uri = found.get("jwks_uri")
        if not isinstance(uri, str) or not secure(uri):
            raise KeysUnavailableError("the discovery document has no https jwks_uri")
        return uri

    def fetch_keys(self, uri: str) -> dict[str, jwt.PyJWK]:
        """The signing keys by id at uri. Anything but a key set with a usable
        signing key (not JSON, not an object, no keys) is KeysUnavailableError."""
        found = fetch_json(uri)
        if not isinstance(found, dict):
            raise KeysUnavailableError("the key set is not a JSON object")
        try:
            keyset = jwt.PyJWKSet.from_dict(found)
        except jwt.PyJWTError as error:  # no usable keys, or a malformed set
            raise KeysUnavailableError(f"the key set: {error}") from error
        keys = {
            k.key_id: k
            for k in keyset.keys
            if k.key_id and k.public_key_use in ("sig", None)
        }
        if not keys:
            raise KeysUnavailableError("the key set has no signing keys")
        return keys

    def key(self, kid: str) -> jwt.PyJWK:
        with self.lock:
            now = self.clock()
            keys = self.keys
            fresh = keys is not None and now - self.fetched_at < KEYS_LIFESPAN
            if keys is not None and kid in keys and (fresh or self.fetching):
                return keys[kid]  # an expired set too, while its refresh is in flight
            if fresh and now - self.tried_at < COOLDOWN:
                raise InvalidTokenError("an unknown signing key")
            if self.fetching:
                raise KeysUnavailableError("the issuer's keys are being fetched")
            if now - self.failed_at < RETRY:
                raise KeysUnavailableError("fetching the issuer's keys failed just now")
            self.fetching, self.tried_at, known = True, now, self.jwks_uri
        try:
            uri = self.discover(known)
            fetched = self.fetch_keys(uri)
        except BaseException:
            with self.lock:
                self.fetching, self.failed_at = False, self.clock()
                if self.clock() - self.fetched_at >= KEYS_LIFESPAN:
                    self.keys = None  # expired, and its refresh failed
            raise
        with self.lock:
            self.fetching, self.jwks_uri = False, uri
            self.keys, self.fetched_at = fetched, self.clock()
        if kid not in fetched:
            raise InvalidTokenError("an unknown signing key")
        return fetched[kid]

    def signing_key(self, token: str) -> jwt.PyJWK:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as error:
            raise InvalidTokenError("not a token") from error
        if not isinstance(kid, str):
            raise InvalidTokenError("the token names no key")
        return self.key(kid)

    def verify(self, token: str) -> str:
        """The token's username, lower-cased, if it lets its holder in; else
        InvalidTokenError (KeysUnavailableError when the keys cannot be had)."""
        key = self.signing_key(token)
        if key.algorithm_name not in ALGORITHMS:
            raise InvalidTokenError(f"a {key.algorithm_name} key")
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=[key.algorithm_name],  # the one this key is for
                issuer=self.conf.issuer,
                leeway=LEEWAY,
                options={"require": ["exp", "iat", "iss"], "verify_aud": False},
            )
        except jwt.PyJWTError as error:
            raise InvalidTokenError(str(error)) from error
        aud = claims.get("aud", [])
        auds = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
        if claims.get("azp") != self.conf.client_id and self.conf.client_id not in auds:
            raise InvalidTokenError("the token was issued to another client")
        typ = claims.get("typ")
        if not isinstance(typ, str) or typ.lower() != "bearer":
            raise InvalidTokenError("not an access token")
        user = claims.get("preferred_username")
        if not isinstance(user, str) or user.strip().lower() not in self.conf.allowed:
            raise InvalidTokenError("this login may not use this scrap")
        return user.strip().lower()


def exempt(path: str) -> bool:
    """/healthz (probes) and /mcp, /mcp/... (the bearer token's, ADR 23)."""
    return path == "/healthz" or path == "/mcp" or path.startswith("/mcp/")


class OidcGate:
    """ASGI middleware: the token check above on every HTTP request but exempt()'s.
    The checked username goes in scope[USER]."""

    def __init__(self, app: ASGIApp, verifier: Verifier) -> None:
        self.app = app
        self.verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if (root := scope.get("root_path", "")) and path.startswith(root):
            path = path[len(root) :]  # as BearerAuth does
        if scope["type"] == "http" and exempt(path):
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":  # a websocket: scrap has none, so refuse it
            await send({"type": "websocket.close", "code": 1008})
            return
        user = await self.check(scope, path)
        if isinstance(user, Response):
            await user(scope, receive, send)
            return
        scope[USER] = user
        await self.app(scope, receive, send)

    async def check(self, scope: Scope, path: str) -> str | Response:
        """The request's checked username, or the refusal to send."""
        method = scope.get("method")
        tokens = [v for k, v in scope["headers"] if k == HEADER]
        try:
            if len(tokens) != 1 or not tokens[0].strip():
                raise InvalidTokenError("no token")
            token = tokens[0].decode("latin-1").strip()
            return await anyio.to_thread.run_sync(self.verifier.verify, token)
        except InvalidTokenError as error:  # the token is never logged
            log.warning("Refused %s %s: %s", method, path, error)
            return refusal(path, "Unauthorized", 401)
        except KeysUnavailableError as error:
            log.error("Refused %s %s: %s", method, path, error)
            return refusal(path, "The login's keys are unavailable", 503)
        except Exception:  # never let a request through on a bug
            log.exception("Refused %s %s: the token check failed", method, path)
            return refusal(path, "Unauthorized", 401)


def refusal(path: str, message: str, status: int) -> Response:
    """JSON for the API, plain text otherwise; never cached."""
    headers = {"Cache-Control": "no-store"}
    if path == "/api" or path.startswith("/api/"):
        return JSONResponse({"detail": message}, status, headers)
    return PlainTextResponse(message, status, headers)
