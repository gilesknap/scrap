"""The login proxy's Keycloak token, checked by scrap (oidc, ADR 45): a fake issuer
whose keys are made here, so nothing touches the network."""

import base64
import http.server
import threading
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from starlette.websockets import WebSocketDisconnect

from scrap import oidc
from scrap.app import create_app
from scrap.store import Store, new_ulid

ISSUER = "https://identity.example.org/realms/dls"
JWKS_URI = ISSUER + "/protocol/openid-connect/certs"
CLIENT = "scrap"
OWNER = "abc12345"  # a DLS fedid: the Keycloak username
HEADER = "X-Auth-Request-Access-Token"
MCP_TOKEN = "an-mcp-bearer-token"

RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
EC_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SECRET = b"a shared secret that must never be a key here, 32+ bytes"


def jwk(key: Any, kid: str) -> dict[str, Any]:
    alg = RSAAlgorithm if kid.startswith("rsa") else ECAlgorithm
    found = alg.to_jwk(key.public_key(), as_dict=True)
    return {**found, "kid": kid, "use": "sig"}


OCT = {"kty": "oct", "kid": "oct", "use": "sig",
       "k": base64.urlsafe_b64encode(SECRET).rstrip(b"=").decode()}  # fmt: skip
ENC = {**jwk(OTHER_KEY, "rsa-enc"), "use": "enc"}  # an encryption key: never used
JWKS = {"keys": [jwk(RSA_KEY, "rsa1"), jwk(EC_KEY, "ec1"), OCT, ENC]}


def claims(**over: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {"iss": ISSUER, "aud": "account", "azp": CLIENT, "iat": now,
            "exp": now + 300, "preferred_username": OWNER,
            "email": "first.last@example.org", "email_verified": False,
            "typ": "Bearer"}  # fmt: skip
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def token(key: Any = RSA_KEY, alg: str = "RS256", kid: str = "rsa1", **over: Any):
    return jwt.encode(claims(**over), key, algorithm=alg, headers={"kid": kid})


@pytest.fixture
def issuer(monkeypatch):
    """The fake issuer: counts its fetches, and fails them when `down` is set."""
    state: dict[str, Any] = {"discovery": 0, "keys": 0, "down": False}

    def fetch_json(url: str) -> Any:
        if url == ISSUER + "/.well-known/openid-configuration":
            state["discovery"] += 1
            if state["down"]:
                raise oidc.KeysUnavailableError("down")
            uri = state.get("jwks_uri", JWKS_URI)
            return {"issuer": state.get("issuer", ISSUER), "jwks_uri": uri}
        assert url == JWKS_URI
        state["keys"] += 1
        if "gate" in state:  # a fetch held in flight until the test lets it go
            state["started"].set()
            assert state["gate"].wait(10)
        if state["down"] or state.get("keys_down"):
            raise oidc.KeysUnavailableError("down")
        return state.get("jwks", JWKS)

    monkeypatch.setattr(oidc, "fetch_json", fetch_json)
    monkeypatch.setenv("SCRAP_MCP_TOKEN", MCP_TOKEN)
    monkeypatch.setenv("SCRAP_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("SCRAP_OIDC_CLIENT_ID", CLIENT)
    # a second user with a k: the Kelvin sign lower-cases to it, and must not let in
    monkeypatch.setenv("SCRAP_ALLOWED_USERS", f" {OWNER} ,kxy98765")
    return state


@pytest.fixture
def gated(issuer, tmp_path):
    return TestClient(create_app(tmp_path / "data"))


def get(client: TestClient, tok: str | None, path: str = "/api/pages", **headers):
    if tok is not None:
        headers[HEADER] = tok
    return client.get(path, headers=headers)


# ---- off


def test_off_without_an_issuer(client):
    assert client.get("/api/pages").status_code == 200
    assert client.get("/").status_code != 401  # the PWA (if built)


# ---- refused


def test_no_token_is_401_json_on_the_api_and_text_elsewhere(gated):
    r = get(gated, None)
    assert r.status_code == 401
    assert r.json() == {"detail": "Unauthorized"}
    assert r.headers["cache-control"] == "no-store"
    r = get(gated, None, "/")
    assert r.status_code == 401
    assert r.text == "Unauthorized"
    assert "location" not in r.headers  # no redirect: the Ingress does the login
    assert get(gated, "", "/").status_code == 401


def test_a_forged_email_header_alone_does_nothing(gated, monkeypatch):
    monkeypatch.setenv("SCRAP_IDENTITY_HEADER", "X-Auth-Request-Email")
    assert get(gated, None, **{"X-Auth-Request-Email": OWNER}).status_code == 401


@pytest.mark.parametrize(
    "tok",
    [
        pytest.param(lambda: token(OTHER_KEY), id="bad-signature"),
        pytest.param(lambda: "not.a.token", id="garbage"),
        pytest.param(lambda: token(kid="rsa9"), id="unknown-kid"),
        pytest.param(lambda: jwt.encode(claims(), RSA_KEY, "RS256"), id="no-kid"),
        pytest.param(
            lambda: jwt.encode(
                claims(), "", algorithm="none", headers={"kid": "rsa1"}
            ),  # fmt: skip
            id="alg-none",
        ),
        pytest.param(lambda: token(SECRET, "HS256", "rsa1"), id="hs256-on-rsa-key"),
        pytest.param(lambda: token(SECRET, "HS256", "oct"), id="hs256-shared-key"),
        pytest.param(lambda: token(RSA_KEY, "RS256", "ec1"), id="rs256-on-ec-key"),
        pytest.param(lambda: token(iss=ISSUER + "/"), id="wrong-iss"),
        pytest.param(lambda: token(iss=None), id="no-iss"),
        pytest.param(lambda: token(azp="other", aud="account"), id="wrong-azp-aud"),
        pytest.param(lambda: token(azp=None, aud=["account", "x"]), id="no-azp"),
        pytest.param(lambda: token(exp=int(time.time()) - 60), id="expired"),
        pytest.param(lambda: token(exp=None), id="no-exp"),
        pytest.param(lambda: token(iat=None), id="no-iat"),
        pytest.param(lambda: token(nbf=int(time.time()) + 120), id="not-yet-valid"),
        pytest.param(lambda: token(preferred_username="zzz11111"), id="not-allowed"),
        pytest.param(lambda: token(preferred_username=None), id="no-username"),
        pytest.param(lambda: token(preferred_username=["abc12345"]), id="not-a-string"),
        pytest.param(lambda: token(preferred_username=""), id="empty-username"),
        # the claim is not folded: only the exact lower-case ASCII name lets in
        pytest.param(
            lambda: token(preferred_username=OWNER + " "), id="trailing-space"
        ),
        pytest.param(lambda: token(preferred_username=OWNER + "\u00a0"), id="nbsp"),
        pytest.param(lambda: token(preferred_username=OWNER.upper()), id="upper-case"),
        pytest.param(
            lambda: token(preferred_username="\u212axy98765"), id="kelvin-sign"
        ),
        pytest.param(
            lambda: token(preferred_username="zzz11111", email_verified=True),
            id="not-allowed-email-verified",
        ),
        pytest.param(
            lambda: token(preferred_username=None, email=OWNER), id="email-not-username"
        ),
        pytest.param(lambda: token(typ="ID"), id="an-id-token"),
        pytest.param(lambda: token(typ=None), id="no-typ"),
        pytest.param(lambda: token(OTHER_KEY, kid="rsa-enc"), id="an-enc-key"),
    ],
)
def test_a_token_that_does_not_let_in_is_401(gated, tok):
    assert get(gated, tok()).status_code == 401
    assert get(gated, tok(), "/").status_code == 401


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "POST", "DELETE"])
def test_every_method_needs_the_token(gated, method):
    assert gated.request(method, "/api/pages").status_code == 401
    assert gated.request(method, "/").status_code == 401


def test_a_websocket_is_refused(gated):
    with pytest.raises(WebSocketDisconnect):
        with gated.websocket_connect("/ws", headers={HEADER: token()}):
            pass


def test_two_tokens_are_refused(gated):
    good = token()
    r = gated.get("/api/pages", headers=[(HEADER, good), (HEADER, good)])
    assert r.status_code == 401


def test_keys_that_cannot_be_fetched_are_503(gated, issuer):
    issuer["down"] = True
    assert get(gated, token()).status_code == 503
    assert get(gated, token(), "/").status_code == 503
    assert issuer["discovery"] == 1
    assert get(gated, token()).status_code == 503  # discovery is not retried at once
    assert issuer["discovery"] == 1


def test_keys_that_cannot_be_fetched_after_discovery_are_503(gated, issuer):
    issuer["keys_down"] = True
    assert get(gated, token()).status_code == 503
    assert issuer["discovery"] == 1


@pytest.mark.parametrize(
    "jwks", [["a list"], "text", None, {"keys": []}, {"keys": [{"kty": "x"}]}]
)
def test_a_key_set_that_is_not_one_is_503(gated, issuer, jwks):
    issuer["jwks"] = jwks  # (fetch_json's own bad JSON is KeysUnavailableError)
    assert get(gated, token()).status_code == 503


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def verifier(issuer):
    conf = oidc.settings(mcp_guarded=True)
    assert conf
    v = oidc.Verifier(conf)
    v.clock = Clock()
    return v


def outcome(v: oidc.Verifier, tok: str) -> str:
    try:
        v.verify(tok)
    except oidc.KeysUnavailableError:
        return "503"
    except oidc.InvalidTokenError:
        return "401"
    return "ok"


def test_an_outage_is_fetched_once_per_retry(verifier, issuer):
    clock: Clock = verifier.clock  # type: ignore[assignment]
    assert outcome(verifier, token()) == "ok"
    issuer["keys_down"] = True
    clock.now += oidc.KEYS_LIFESPAN  # the cached set expires during the outage
    assert [outcome(verifier, token()) for _ in range(20)] == ["503"] * 20
    assert issuer["keys"] == 2  # the first fetch, and one failed refetch
    clock.now += oidc.RETRY
    assert outcome(verifier, token()) == "503"
    assert issuer["keys"] == 3
    issuer["keys_down"] = False
    clock.now += oidc.RETRY
    assert outcome(verifier, token()) == "ok"
    assert issuer["keys"] == 4


def test_unknown_key_ids_refetch_once_per_cooldown(verifier, issuer):
    clock: Clock = verifier.clock  # type: ignore[assignment]
    assert outcome(verifier, token()) == "ok"
    junk = [token(kid=f"junk{i}") for i in range(20)]
    assert [outcome(verifier, t) for t in junk] == ["401"] * 20
    assert issuer["keys"] == 1  # within the cooldown of the first fetch
    clock.now += oidc.COOLDOWN
    assert [outcome(verifier, t) for t in junk] == ["401"] * 20
    assert issuer["keys"] == 2
    assert outcome(verifier, token()) == "ok"  # known keys still answer


def test_a_fetch_under_way_is_not_waited_for(verifier, issuer):
    verifier.fetching = True  # another request's fetch
    assert outcome(verifier, token()) == "503"
    assert issuer["keys"] == 0


def in_flight(verifier: oidc.Verifier, issuer: dict[str, Any]):
    """Start a request whose key fetch is held until gate is set; its outcome."""
    issuer["gate"], issuer["started"] = threading.Event(), threading.Event()
    done: list[str] = []
    first = threading.Thread(target=lambda: done.append(outcome(verifier, token())))
    first.start()
    assert issuer["started"].wait(10)
    return first, done


def test_the_first_fetch_is_made_once(verifier, issuer):
    first, done = in_flight(verifier, issuer)
    assert [outcome(verifier, token()) for _ in range(5)] == ["503"] * 5
    issuer["gate"].set()
    first.join(10)
    assert done == ["ok"]
    assert (issuer["discovery"], issuer["keys"]) == (1, 1)


def test_an_expired_set_answers_while_its_refresh_is_in_flight(verifier, issuer):
    clock: Clock = verifier.clock  # type: ignore[assignment]
    assert outcome(verifier, token()) == "ok"
    clock.now += oidc.KEYS_LIFESPAN
    first, done = in_flight(verifier, issuer)
    assert [outcome(verifier, token()) for _ in range(5)] == ["ok"] * 5
    assert outcome(verifier, token(kid="rsa9")) == "503"  # unknown: wait for it
    issuer["gate"].set()
    first.join(10)
    assert done == ["ok"]
    assert issuer["keys"] == 2


def test_an_expired_set_is_dropped_when_its_refresh_fails(verifier, issuer):
    clock: Clock = verifier.clock  # type: ignore[assignment]
    assert outcome(verifier, token()) == "ok"
    clock.now += oidc.KEYS_LIFESPAN - 1
    issuer["keys_down"] = True
    assert outcome(verifier, token(kid="rsa9")) == "503"  # a refetch that fails
    assert outcome(verifier, token()) == "ok"  # the set has not expired: kept
    clock.now += 1
    assert outcome(verifier, token()) == "503"  # expired, and in RETRY
    clock.now += oidc.RETRY
    assert outcome(verifier, token()) == "503"  # its refresh fails: dropped
    issuer["keys_down"] = False
    assert outcome(verifier, token()) == "503"  # in RETRY, and no set to answer
    clock.now += oidc.RETRY
    assert outcome(verifier, token()) == "ok"


def test_a_rotated_key_is_picked_up_after_the_cooldown(verifier, issuer):
    clock: Clock = verifier.clock  # type: ignore[assignment]
    assert outcome(verifier, token()) == "ok"
    issuer["jwks"] = {"keys": [jwk(OTHER_KEY, "rsa2")]}  # Keycloak rotates
    new = token(OTHER_KEY, kid="rsa2")
    assert outcome(verifier, new) == "401"  # within the first fetch's cooldown
    clock.now += oidc.COOLDOWN
    assert outcome(verifier, new) == "ok"
    assert outcome(verifier, token()) == "401"  # the old key is gone
    assert issuer["keys"] == 2


@pytest.mark.parametrize(
    "uri",
    ["http://identity.example.org/certs", "file:///etc/passwd", None],
)
def test_a_jwks_uri_that_is_not_https_is_503(verifier, issuer, uri):
    issuer["jwks_uri"] = uri
    assert outcome(verifier, token()) == "503"
    assert issuer["keys"] == 0


@pytest.fixture
def server():
    """A local HTTP server; the handler's behaviour is set per test."""
    behaviour: dict[str, Any] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = behaviour["body"]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            step = behaviour.get("chunk") or len(body) or 1
            for i in range(0, len(body), step):
                self.wfile.write(body[i : i + step])
                self.wfile.flush()
                time.sleep(behaviour.get("pause", 0))

        def log_message(self, format: str, *args: Any) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    behaviour["url"] = f"http://127.0.0.1:{httpd.server_address[1]}/"
    yield behaviour
    httpd.shutdown()
    httpd.server_close()


def test_fetch_json_reads_json(server):
    server["body"] = b'{"keys": []}'
    assert oidc.fetch_json(server["url"]) == {"keys": []}


def test_fetch_json_caps_the_size(server, monkeypatch):
    monkeypatch.setattr(oidc, "MAX_BYTES", 1000)
    server["body"] = b'{"k": "' + b"x" * 5000 + b'"}'
    with pytest.raises(oidc.KeysUnavailableError, match="over 1000 bytes"):
        oidc.fetch_json(server["url"])


def test_fetch_json_has_an_overall_deadline(server, monkeypatch):
    monkeypatch.setattr(oidc, "DEADLINE", 0.3)
    server.update(body=b'{"k": "' + b"x" * 40 + b'"}', chunk=2, pause=0.05)
    started = time.monotonic()
    with pytest.raises(oidc.KeysUnavailableError, match="took over"):
        oidc.fetch_json(server["url"])
    assert time.monotonic() - started < 1  # each piece is quick: only the total


def test_fetch_json_refuses_what_is_not_json(server):
    server["body"] = b"<html>"
    with pytest.raises(oidc.KeysUnavailableError):
        oidc.fetch_json(server["url"])


def test_discovery_for_another_issuer_is_503(gated, issuer):
    issuer["issuer"] = "https://evil.example.org/realms/dls"
    assert get(gated, token()).status_code == 503


# ---- let in


def test_a_good_token_lets_in_and_its_username_is_the_author(gated, issuer, tmp_path):
    good = token(preferred_username=OWNER)
    assert get(gated, good).status_code == 200
    r = gated.post(
        "/api/captures",
        json={"id": new_ulid(), "text": "Shopping\nmilk"},
        headers={
            HEADER: good,
            "Tailscale-User-Login": "forged@example.org",
            "X-Auth-Request-Email": "forged@example.org",
        },  # fmt: skip
    )
    assert r.status_code == 201, r.text
    page = r.json()["page_id"]
    text = Store(tmp_path / "data").revisions(page)["text"]
    assert [t["author"] for t in text] == [OWNER]
    assert (issuer["discovery"], issuer["keys"]) == (1, 1)  # cached after


@pytest.mark.parametrize(
    "tok",
    [
        pytest.param(lambda: token(EC_KEY, "ES256", "ec1"), id="es256"),
        pytest.param(lambda: token(azp=None, aud=["account", CLIENT]), id="aud"),
        pytest.param(lambda: token(aud=None), id="azp-only"),
        pytest.param(lambda: token(exp=int(time.time()) - 10), id="within-leeway"),
        # DLS's Keycloak does not verify emails: the username is the gate
        pytest.param(lambda: token(email_verified=False), id="email-unverified"),
        pytest.param(lambda: token(email_verified=None), id="email-verified-missing"),
        pytest.param(lambda: token(email=None), id="no-email"),
        pytest.param(lambda: token(preferred_username="kxy98765"), id="second-user"),
    ],
)
def test_other_good_tokens(gated, tok):
    assert get(gated, tok()).status_code == 200


def test_healthz_and_mcp_need_no_login_token(issuer, tmp_path):
    with TestClient(create_app(tmp_path / "data")) as gated:
        exempt(gated)


def exempt(gated: TestClient) -> None:
    assert get(gated, None, "/healthz").status_code == 200
    accept = {"Accept": "application/json, text/event-stream"}
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    # /mcp needs its bearer token instead (ADR 23), which the start insists on
    assert gated.post("/mcp", json=ping, headers=accept).status_code == 401
    bearer = {**accept, "Authorization": f"Bearer {MCP_TOKEN}"}
    assert gated.post("/mcp", json=ping, headers=bearer).status_code == 200
    assert get(gated, None, "/mcp/blobs/x").status_code == 401
    blob = get(gated, None, "/mcp/blobs/x", Authorization=f"Bearer {MCP_TOKEN}")
    assert blob.status_code not in (401, 503)
    assert get(gated, None, "/mcpx").status_code == 401
    assert get(gated, None, "/healthz/x").status_code == 401


def test_the_root_path_is_minded(issuer, tmp_path):
    client = TestClient(create_app(tmp_path / "data"), root_path="/scrap")
    assert client.get("/scrap/healthz").status_code == 200
    assert client.get("/scrap/api/pages").status_code == 401
    r = client.get("/scrap/api/pages", headers={HEADER: token()})
    assert r.status_code == 200


# ---- start


@pytest.mark.parametrize(
    "name, value, said",
    [
        ("SCRAP_ALLOWED_USERS", " , ", "SCRAP_ALLOWED_USERS is empty"),
        ("SCRAP_ALLOWED_USERS", None, "SCRAP_ALLOWED_USERS is empty"),
        ("SCRAP_OIDC_CLIENT_ID", " ", "SCRAP_OIDC_CLIENT_ID is empty"),
        ("SCRAP_OIDC_ISSUER", "http://identity.example.org", "https"),
        ("SCRAP_MCP_TOKEN", None, "no bearer token"),
    ],
)
def test_a_missing_setting_stops_the_start(issuer, tmp_path, monkeypatch, name,
                                           value, said):  # fmt: skip
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit, match=said):
        create_app(tmp_path / "data")


def test_a_loopback_issuer_may_be_http(monkeypatch):
    monkeypatch.setenv("SCRAP_OIDC_ISSUER", "http://localhost:8080/realms/dev")
    monkeypatch.setenv("SCRAP_OIDC_CLIENT_ID", CLIENT)
    monkeypatch.setenv("SCRAP_ALLOWED_USERS", "ABC12345")
    conf = oidc.settings(mcp_guarded=True)
    assert conf and conf.allowed == frozenset({"abc12345"})


def test_fetch_json_takes_http_only():
    with pytest.raises(oidc.KeysUnavailableError):
        oidc.fetch_json("file:///etc/passwd")
