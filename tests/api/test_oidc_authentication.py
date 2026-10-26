from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ragguard.auth import oidc
from ragguard.auth.repository import InMemoryAuthRepository


ISSUER = "https://identity.example.test"
CLIENT_ID = "ragguard-test"
FRONTEND = "https://dashboard.example.test"
REDIRECT = "https://api.example.test/api/v1/auth/callback"


def configure_oidc(monkeypatch):
    monkeypatch.setenv("RAGGUARD_CONFIG", "configs/testing.yaml")
    monkeypatch.setenv("RAGGUARD_AUTH_MODE", "oidc")
    monkeypatch.setenv("RAGGUARD_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("RAGGUARD_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("RAGGUARD_OIDC_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("RAGGUARD_OIDC_REDIRECT_URI", REDIRECT)
    monkeypatch.setenv("RAGGUARD_FRONTEND_URL", FRONTEND)
    monkeypatch.setenv("RAGGUARD_SESSION_SECRET", "x" * 48)
    monkeypatch.setenv("RAGGUARD_SESSION_COOKIE_SECURE", "true")


class FakeOIDCClient:
    token: str
    jwk: dict

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, request=httpx.Request("GET", url), json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/keys",
            })
        if url == f"{ISSUER}/keys":
            return httpx.Response(200, request=httpx.Request("GET", url), json={"keys": [self.jwk]})
        raise AssertionError(f"Unexpected provider URL: {url}")

    async def post(self, url, **kwargs):
        assert url == f"{ISSUER}/token"
        assert kwargs["data"]["code_verifier"]
        return httpx.Response(200, request=httpx.Request("POST", url), json={"id_token": self.token})


def setup_client(monkeypatch, token_subject="user-123", *, issuer=ISSUER, audience=CLIENT_ID, nonce="placeholder", expired=False):
    configure_oidc(monkeypatch)
    repository = InMemoryAuthRepository()
    monkeypatch.setattr(oidc, "auth_repository", repository)
    key = rsa_private_key_for_test
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    public_jwk["kid"] = "test-key"
    expires = datetime.now(timezone.utc) - timedelta(minutes=1) if expired else datetime.now(timezone.utc) + timedelta(minutes=5)
    FakeOIDCClient.token = jwt.encode({
        "iss": issuer,
        "sub": token_subject,
        "aud": audience,
        "iat": datetime.now(timezone.utc),
        "exp": expires,
        "nonce": nonce,
    }, key, algorithm="RS256", headers={"kid": "test-key"})
    FakeOIDCClient.jwk = public_jwk
    monkeypatch.setattr(oidc.httpx, "AsyncClient", FakeOIDCClient)
    test_app = FastAPI()
    test_app.include_router(oidc.router, prefix="/api/v1")
    return TestClient(test_app, base_url="https://api.example.test"), repository


def start_flow(client: TestClient):
    response = client.get("/api/v1/auth/login", follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query


def test_oidc_login_uses_state_nonce_and_pkce_then_creates_httponly_session(monkeypatch):
    client, repository = setup_client(monkeypatch)
    query = start_flow(client)
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["nonce"]
    FakeOIDCClient.token = jwt.encode({
        "iss": ISSUER,
        "sub": "user-123",
        "aud": CLIENT_ID,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "nonce": query["nonce"][0],
    }, rsa_private_key_for_test, algorithm="RS256", headers={"kid": "test-key"})

    response = client.get(
        "/api/v1/auth/callback",
        params={"code": "authorization-code", "state": query["state"][0]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == FRONTEND
    cookie = response.headers["set-cookie"]
    assert "ragguard_session=" in cookie
    assert "httponly" in cookie.lower()
    assert "secure" in cookie.lower()
    session = client.get("/api/v1/auth/session").json()
    assert session["authenticated"] is True
    assert session["subject"] == "user-123"
    assert session["csrf_token"]
    assert repository.get_session(client.cookies.get("ragguard_session")) is not None


@pytest.mark.parametrize("bad", ["issuer", "audience", "expired"])
def test_oidc_callback_rejects_bad_issuer_audience_or_expiration(monkeypatch, bad):
    kwargs = {
        "issuer": "https://attacker.example.test" if bad == "issuer" else ISSUER,
        "audience": "some-other-client" if bad == "audience" else CLIENT_ID,
        "expired": bad == "expired",
    }
    client, _ = setup_client(monkeypatch, **kwargs)
    query = start_flow(client)
    expires = datetime.now(timezone.utc) - timedelta(minutes=1) if kwargs["expired"] else datetime.now(timezone.utc) + timedelta(minutes=5)
    FakeOIDCClient.token = jwt.encode({
        "iss": kwargs["issuer"], "sub": "user-123", "aud": kwargs["audience"],
        "iat": datetime.now(timezone.utc), "exp": expires, "nonce": query["nonce"][0],
    }, rsa_private_key_for_test, algorithm="RS256", headers={"kid": "test-key"})
    response = client.get(
        "/api/v1/auth/callback",
        params={"code": "authorization-code", "state": query["state"][0]},
        follow_redirects=False,
    )
    assert response.status_code == 401


def test_oidc_callback_requires_matching_browser_state_cookie(monkeypatch):
    client, _ = setup_client(monkeypatch)
    query = start_flow(client)
    client.cookies.delete("ragguard_oidc_state")
    response = client.get("/api/v1/auth/callback", params={"code": "code", "state": query["state"][0]})
    assert response.status_code == 401


def test_oidc_callback_rejects_nonce_mismatch(monkeypatch):
    client, _ = setup_client(monkeypatch)
    query = start_flow(client)
    FakeOIDCClient.token = jwt.encode({
        "iss": ISSUER, "sub": "user-123", "aud": CLIENT_ID,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "nonce": "different-login-flow",
    }, rsa_private_key_for_test, algorithm="RS256", headers={"kid": "test-key"})
    response = client.get(
        "/api/v1/auth/callback",
        params={"code": "authorization-code", "state": query["state"][0]},
        follow_redirects=False,
    )
    assert response.status_code == 401


# Assigned after helper setup to keep a single key pair shared by token and JWKS.
rsa_private_key_for_test = rsa.generate_private_key(public_exponent=65537, key_size=2048)
