"""OIDC authorization-code flow with PKCE and verified ID tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from ragguard.api.runtime import auth_repository
from ragguard.config import load_settings

router = APIRouter(prefix="/auth", tags=["authentication"])
_STATE_COOKIE = "ragguard_oidc_state"


def _settings():
    settings = load_settings().authentication
    required = {
        "RAGGUARD_OIDC_ISSUER": settings.oidc_issuer,
        "RAGGUARD_OIDC_CLIENT_ID": settings.oidc_client_id,
        "RAGGUARD_OIDC_CLIENT_SECRET": settings.oidc_client_secret,
        "RAGGUARD_OIDC_REDIRECT_URI": settings.oidc_redirect_uri,
        "RAGGUARD_FRONTEND_URL": settings.frontend_url,
        "RAGGUARD_SESSION_SECRET": settings.session_secret,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise HTTPException(status_code=503, detail="OIDC authentication is incompletely configured.")
    if settings.mode != "oidc":
        raise HTTPException(status_code=404, detail="OIDC authentication is not enabled.")
    return settings


def _require_https_endpoint(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=503, detail="OIDC provider metadata contains an unsafe endpoint.")


def _allowed_return_to(value: str, settings) -> str:
    candidate = value or settings.frontend_url
    parsed = urlparse(candidate)
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    allowed = {settings.frontend_url.rstrip("/"), *settings.frontend_origins}
    if parsed.scheme not in {"https", "http"} or origin not in allowed or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="The requested post-login URL is not allowed.")
    return candidate


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _csrf_for(session_id: str, settings) -> str:
    return _b64url(hmac.new(settings.session_secret.encode(), session_id.encode(), hashlib.sha256).digest())


def _cookie(response: Response, name: str, value: str, settings, *, max_age: int, http_only: bool = True):
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=http_only,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


@router.get("/login")
async def login(request: Request, return_to: str | None = None):
    settings = _settings()
    target = _allowed_return_to(return_to or settings.frontend_url, settings)
    issuer = settings.oidc_issuer
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        try:
            discovery_response = await client.get(f"{issuer}/.well-known/openid-configuration")
            discovery_response.raise_for_status()
            metadata = discovery_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="OIDC provider discovery failed.") from exc
    if metadata.get("issuer") != issuer:
        raise HTTPException(status_code=503, detail="OIDC discovery issuer did not match configuration.")
    _require_https_endpoint(metadata.get("authorization_endpoint", ""))
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    auth_repository.save_flow(state, {
        "nonce": nonce,
        "code_verifier": verifier,
        "return_to": target,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    })
    query = urlencode({
        "client_id": settings.oidc_client_id,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": settings.oidc_redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    response = RedirectResponse(f"{metadata['authorization_endpoint']}?{query}", status_code=302)
    _cookie(response, _STATE_COOKIE, state, settings, max_age=300)
    return response


@router.get("/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    settings = _settings()
    if error or not code or not state or not secrets.compare_digest(state, request.cookies.get(_STATE_COOKIE, "")):
        raise HTTPException(status_code=401, detail="OIDC login could not be verified.")
    flow = auth_repository.consume_flow(state)
    if not flow or flow["expires_at"] <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="OIDC login expired. Please try again.")
    issuer = settings.oidc_issuer
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        try:
            discovery_response = await client.get(f"{issuer}/.well-known/openid-configuration")
            discovery_response.raise_for_status()
            metadata = discovery_response.json()
            if metadata.get("issuer") != issuer:
                raise ValueError("issuer mismatch")
            _require_https_endpoint(metadata.get("token_endpoint", ""))
            _require_https_endpoint(metadata.get("jwks_uri", ""))
            token_form = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oidc_redirect_uri,
                "code_verifier": flow["code_verifier"],
            }
            if settings.oidc_token_auth_method == "client_secret_post":
                token_form.update({"client_id": settings.oidc_client_id, "client_secret": settings.oidc_client_secret})
                token_response = await client.post(metadata["token_endpoint"], data=token_form)
            else:
                token_form["client_id"] = settings.oidc_client_id
                token_response = await client.post(
                    metadata["token_endpoint"],
                    data=token_form,
                    auth=(settings.oidc_client_id, settings.oidc_client_secret),
                )
            token_response.raise_for_status()
            tokens = token_response.json()
            id_token = tokens["id_token"]
            header = jwt.get_unverified_header(id_token)
            if header.get("alg") not in {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}:
                raise ValueError("unsupported signing algorithm")
            jwks_response = await client.get(metadata["jwks_uri"])
            jwks_response.raise_for_status()
            jwks = jwks_response.json().get("keys", [])
            jwk = next((item for item in jwks if item.get("kid") == header.get("kid")), None)
            if jwk is None:
                raise ValueError("signing key not found")
            signing_key = jwt.PyJWK.from_dict(jwk, algorithm=header["alg"]).key
            claims = jwt.decode(
                id_token,
                signing_key,
                algorithms=[header["alg"]],
                audience=settings.oidc_client_id,
                issuer=issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
                leeway=60,
            )
            if not secrets.compare_digest(str(claims.get("nonce", "")), flow["nonce"]):
                raise ValueError("nonce mismatch")
            authorized_party = claims.get("azp")
            if authorized_party is not None and authorized_party != settings.oidc_client_id:
                raise ValueError("authorized party mismatch")
            if isinstance(claims.get("aud"), list) and len(claims["aud"]) > 1 and authorized_party != settings.oidc_client_id:
                raise ValueError("authorized party mismatch")
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject:
                raise ValueError("missing subject")
        except (httpx.HTTPError, KeyError, ValueError, jwt.PyJWTError) as exc:
            raise HTTPException(status_code=401, detail="OIDC token verification failed.") from exc

    session_id = secrets.token_urlsafe(48)
    csrf_token = _csrf_for(session_id, settings)
    auth_repository.save_session(session_id, {
        "issuer": issuer,
        "subject": subject,
        "csrf_hash": hashlib.sha256(csrf_token.encode()).hexdigest(),
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds),
    })
    response = RedirectResponse(flow["return_to"], status_code=303)
    _cookie(response, settings.session_cookie_name, session_id, settings, max_age=settings.session_ttl_seconds)
    response.delete_cookie(_STATE_COOKIE, path="/", secure=settings.session_cookie_secure, httponly=True, samesite=settings.session_cookie_samesite)
    return response


@router.get("/session")
def current_session(request: Request):
    loaded = load_settings()
    if loaded.authentication.mode != "oidc":
        return {"authentication_required": False, "authenticated": False}
    settings = _settings()
    session_id = request.cookies.get(settings.session_cookie_name)
    record = auth_repository.get_session(session_id) if session_id else None
    if not record:
        return {"authentication_required": True, "authenticated": False}
    roles = auth_repository.get_membership(
        record["issuer"], record["subject"], load_settings().service_auth.tenant_id
    ) or ()
    return {
        "authentication_required": True,
        "authenticated": True,
        "issuer": record["issuer"],
        "subject": record["subject"],
        "csrf_token": _csrf_for(session_id, settings),
        "administrator": bool({role.lower() for role in roles} & {"admin", "owner", "workspace_admin"}),
    }


@router.post("/logout")
def logout(request: Request, response: Response):
    settings = _settings()
    session_id = request.cookies.get(settings.session_cookie_name)
    record = auth_repository.get_session(session_id) if session_id else None
    supplied = request.headers.get("X-CSRF-Token", "")
    if not record or not secrets.compare_digest(record.get("csrf_hash", ""), hashlib.sha256(supplied.encode()).hexdigest()):
        raise HTTPException(status_code=403, detail="CSRF verification failed.")
    auth_repository.delete_session(session_id)
    response.delete_cookie(settings.session_cookie_name, path="/", secure=settings.session_cookie_secure, httponly=True, samesite=settings.session_cookie_samesite)
    return {"authenticated": False}
