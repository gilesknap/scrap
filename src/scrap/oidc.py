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
- carries `email_verified: true` and an `email` in `$SCRAP_ALLOWED_EMAILS` (comma
  separated; compared lower-cased).

Otherwise 401 (JSON under /api, else plain text; no redirect, the Ingress does the
login), or 503 when the keys cannot be fetched: never let through on an error. The
verified email is the author of a change (uploads.author). Unset: nothing changes.

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

__all__ = ["EMAIL", "OidcGate", "Settings", "Verifier", "enabled", "settings"]

log = logging.getLogger(__name__)

HEADER = b"x-auth-request-access-token"
EMAIL = "scrap.oidc_email"  # the scope key the verified email is kept under
ALGORITHMS = ("RS256", "ES256")
LEEWAY = 30  # seconds of clock skew allowed on exp, nbf and iat
TIMEOUT = 5  # seconds for each fetch from the issuer
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
    raw = os.environ.get("SCRAP_ALLOWED_EMAILS", "")
    allowed = frozenset(e.strip().lower() for e in raw.split(",") if e.strip())
    parts = urlsplit(issuer)
    if parts.scheme != "https" and not (
        parts.scheme == "http" and parts.hostname in LOOPBACK
    ):
        raise SystemExit(f"SCRAP_OIDC_ISSUER must be an https URL, not {issuer!r}")
    if not client_id:
        raise SystemExit("SCRAP_OIDC_ISSUER is set but SCRAP_OIDC_CLIENT_ID is empty")
    if not allowed:
        raise SystemExit("SCRAP_OIDC_ISSUER is set but SCRAP_ALLOWED_EMAILS is empty")
    if not mcp_guarded:
        raise SystemExit(
            "SCRAP_OIDC_ISSUER is set but /mcp has no bearer token: set SCRAP_MCP_TOKEN"
            " or SCRAP_MCP_TOKEN_FILE, or /mcp is open to anyone who can reach scrap"
        )
    return Settings(issuer, client_id, allowed)


def fetch_json(url: str) -> Any:
    """GET url's JSON: http(s) only, no redirects (as PyJWKClient), TIMEOUT."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise KeysUnavailableError(f"not an http(s) URL: {url!r}")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None

    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except (OSError, ValueError) as error:  # URLError, timeouts, bad JSON
        raise KeysUnavailableError(f"cannot fetch {url}: {error}") from error


class Verifier:
    """Checks a token against Settings. The issuer's keys are found on first use (so
    a Keycloak outage at start is a 503, not a crash loop) and kept KEYS_LIFESPAN.

    scrap's own back-off bounds the fetches, whatever tokens arrive: one fetch at a
    time, each at most TIMEOUT, never holding the lock (a request meanwhile that the
    cached keys cannot answer gets 503 at once); after a failed fetch, none for RETRY
    seconds (503); and a key id not in the set refetches it at most once per
    COOLDOWN (401 meanwhile)."""

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
        if not isinstance(uri, str) or urlsplit(uri).scheme not in ("http", "https"):
            raise KeysUnavailableError("the discovery document has no jwks_uri")
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
            keys = self.keys if now - self.fetched_at < KEYS_LIFESPAN else None
            if keys is not None and kid in keys:
                return keys[kid]
            if keys is not None and now - self.tried_at < COOLDOWN:
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
        """The token's email, lower-cased, if it lets its holder in; else
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
        if claims.get("email_verified") is not True:
            raise InvalidTokenError("the token's email is not verified")
        email = claims.get("email")
        if not isinstance(email, str) or email.strip().lower() not in self.conf.allowed:
            raise InvalidTokenError("this login may not use this scrap")
        return email.strip().lower()


def exempt(path: str) -> bool:
    """/healthz (probes) and /mcp, /mcp/... (the bearer token's, ADR 23)."""
    return path == "/healthz" or path == "/mcp" or path.startswith("/mcp/")


class OidcGate:
    """ASGI middleware: the token check above on every HTTP request but exempt()'s.
    The verified email goes in scope[EMAIL]."""

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
        email = await self.check(scope, path)
        if isinstance(email, Response):
            await email(scope, receive, send)
            return
        scope[EMAIL] = email
        await self.app(scope, receive, send)

    async def check(self, scope: Scope, path: str) -> str | Response:
        """The request's verified email, or the refusal to send."""
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
