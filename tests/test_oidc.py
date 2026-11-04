"""The login proxy's Keycloak token, checked by scrap (oidc, ADR 45): a fake issuer
whose keys are made here, so nothing touches the network."""

import base64
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from scrap import oidc
from scrap.app import create_app
from scrap.store import Store, new_ulid

ISSUER = "https://identity.example.org/realms/dls"
JWKS_URI = ISSUER + "/protocol/openid-connect/certs"
CLIENT = "scrap"
OWNER = "first.last@example.org"
HEADER = "X-Auth-Request-Access-Token"

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
JWKS = {"keys": [jwk(RSA_KEY, "rsa1"), jwk(EC_KEY, "ec1"), OCT]}


def claims(**over: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {"iss": ISSUER, "aud": "account", "azp": CLIENT, "iat": now,
            "exp": now + 300, "email": OWNER, "email_verified": True,
            "typ": "Bearer"}  # fmt: skip
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def token(key: Any = RSA_KEY, alg: str = "RS256", kid: str = "rsa1", **over: Any):
    return jwt.encode(claims(**over), key, algorithm=alg, headers={"kid": kid})


@pytest.fixture
def issuer(monkeypatch):
    """The fake issuer: counts its fetches, and fails them when `down` is set."""
    state = {"discovery": 0, "keys": 0, "down": False}

    def fetch_json(url: str) -> Any:
        assert url == ISSUER + "/.well-known/openid-configuration"
        state["discovery"] += 1
        if state["down"]:
            raise oidc.KeysUnavailableError("down")
        return {"issuer": state.get("issuer", ISSUER), "jwks_uri": JWKS_URI}

    def fetch_data(self: jwt.PyJWKClient) -> Any:
        assert self.uri == JWKS_URI
        state["keys"] += 1
        if state["down"] or state.get("keys_down"):
            raise jwt.PyJWKClientConnectionError("down")
        return JWKS

    monkeypatch.setattr(oidc, "fetch_json", fetch_json)
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_data)
    monkeypatch.setenv("SCRAP_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("SCRAP_OIDC_CLIENT_ID", CLIENT)
    monkeypatch.setenv("SCRAP_ALLOWED_EMAILS", f" {OWNER} ,someone@example.org")
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
        pytest.param(lambda: token(email="other@example.org"), id="not-allowed"),
        pytest.param(lambda: token(email=None), id="no-email"),
        pytest.param(lambda: token(email_verified=False), id="unverified"),
        pytest.param(lambda: token(email_verified=None), id="verified-missing"),
        pytest.param(lambda: token(email_verified="true"), id="verified-a-string"),
    ],
)
def test_a_token_that_does_not_let_in_is_401(gated, tok):
    assert get(gated, tok()).status_code == 401
    assert get(gated, tok(), "/").status_code == 401


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


def test_discovery_for_another_issuer_is_503(gated, issuer):
    issuer["issuer"] = "https://evil.example.org/realms/dls"
    assert get(gated, token()).status_code == 503


# ---- let in


def test_a_good_token_lets_in_and_its_email_is_the_author(gated, issuer, tmp_path):
    good = token(email="First.Last@Example.org")  # compared lower-cased
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
    ],
)
def test_other_good_tokens(gated, tok):
    assert get(gated, tok()).status_code == 200


def test_healthz_and_mcp_need_no_token(issuer, tmp_path):
    with TestClient(create_app(tmp_path / "data")) as gated:
        exempt(gated)


def exempt(gated: TestClient) -> None:
    assert get(gated, None, "/healthz").status_code == 200
    accept = {"Accept": "application/json, text/event-stream"}
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert gated.post("/mcp", json=ping, headers=accept).status_code == 200
    assert get(gated, None, "/mcp/blobs/x").status_code != 401
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
        ("SCRAP_ALLOWED_EMAILS", " , ", "SCRAP_ALLOWED_EMAILS is empty"),
        ("SCRAP_OIDC_CLIENT_ID", " ", "SCRAP_OIDC_CLIENT_ID is empty"),
        ("SCRAP_OIDC_ISSUER", "http://identity.example.org", "https"),
    ],
)
def test_a_missing_setting_stops_the_start(issuer, tmp_path, monkeypatch, name,
                                           value, said):  # fmt: skip
    monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit, match=said):
        create_app(tmp_path / "data")


def test_a_loopback_issuer_may_be_http(monkeypatch):
    monkeypatch.setenv("SCRAP_OIDC_ISSUER", "http://localhost:8080/realms/dev")
    monkeypatch.setenv("SCRAP_OIDC_CLIENT_ID", CLIENT)
    monkeypatch.setenv("SCRAP_ALLOWED_EMAILS", "A@x.org")
    conf = oidc.settings()
    assert conf and conf.allowed == frozenset({"a@x.org"})


def test_fetch_json_takes_http_only():
    with pytest.raises(oidc.KeysUnavailableError):
        oidc.fetch_json("file:///etc/passwd")
