"""OIDC authorization-code flow with PKCE and verified ID tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
import socket
import ssl
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

import anyio
import httpcore
import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from ragguard.api.runtime import auth_repository
from ragguard.config import load_settings

router = APIRouter(prefix="/auth", tags=["authentication"])
_STATE_COOKIE = "ragguard_oidc_state"


class _AnyIONetworkStream(httpcore.AsyncNetworkStream):
    def __init__(self, stream):
        self._stream = stream

    async def read(self, max_bytes, timeout=None):
        try:
            with anyio.fail_after(timeout):
                return await self._stream.receive(max_bytes=max_bytes)
        except anyio.EndOfStream:
            return b""
        except TimeoutError as exc:
            raise httpcore.ReadTimeout("OIDC socket read timed out") from exc
        except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError) as exc:
            raise httpcore.ReadError("OIDC socket read failed") from exc

    async def write(self, buffer, timeout=None):
        if not buffer:
            return
        try:
            with anyio.fail_after(timeout):
                await self._stream.send(buffer)
        except TimeoutError as exc:
            raise httpcore.WriteTimeout("OIDC socket write timed out") from exc
        except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError) as exc:
            raise httpcore.WriteError("OIDC socket write failed") from exc

    async def aclose(self):
        await self._stream.aclose()

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        try:
            with anyio.fail_after(timeout):
                tls_stream = await anyio.streams.tls.TLSStream.wrap(
                    self._stream,
                    ssl_context=ssl_context,
                    hostname=server_hostname,
                    standard_compatible=False,
                    server_side=False,
                )
        except TimeoutError as exc:
            await self.aclose()
            raise httpcore.ConnectTimeout("OIDC TLS handshake timed out") from exc
        except (OSError, ssl.SSLError, anyio.BrokenResourceError, anyio.EndOfStream) as exc:
            await self.aclose()
            raise httpcore.ConnectError("OIDC TLS verification failed") from exc
        return _AnyIONetworkStream(tls_stream)

    def get_extra_info(self, info):
        if info == "ssl_object":
            return self._stream.extra(anyio.streams.tls.TLSAttribute.ssl_object, None)
        if info == "client_addr":
            return self._stream.extra(anyio.abc.SocketAttribute.local_address, None)
        if info == "server_addr":
            return self._stream.extra(anyio.abc.SocketAttribute.remote_address, None)
        if info == "socket":
            return self._stream.extra(anyio.abc.SocketAttribute.raw_socket, None)
        return None


class _AnyIONetworkBackend(httpcore.AsyncNetworkBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            with anyio.fail_after(timeout):
                stream = await anyio.connect_tcp(
                    remote_host=host,
                    remote_port=port,
                    local_host=local_address,
                )
            raw_socket = stream.extra(anyio.abc.SocketAttribute.raw_socket, None)
            for option in socket_options or ():
                if raw_socket is None:
                    raise OSError("TCP socket options are unavailable")
                raw_socket.setsockopt(*option)
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout("OIDC TCP connection timed out") from exc
        except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError) as exc:
            raise httpcore.ConnectError("OIDC TCP connection failed") from exc
        return _AnyIONetworkStream(stream)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("Unix sockets are disabled for OIDC")

    async def sleep(self, seconds):
        await anyio.sleep(seconds)


class _SafeOIDCNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve, validate, and connect to the same IP while retaining TLS SNI."""

    def __init__(self, network_backend=None, resolver=None):
        self._network_backend = network_backend or _AnyIONetworkBackend()
        self._resolver = resolver or anyio.getaddrinfo

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            try:
                addresses = [ipaddress.ip_address(host)]
            except ValueError:
                results = await self._resolver(host, port, type=socket.SOCK_STREAM)
                addresses = [ipaddress.ip_address(result[4][0]) for result in results]
            if not addresses or any(not address.is_global for address in addresses):
                raise ValueError("non-public address")
        except (OSError, TypeError, ValueError) as exc:
            raise httpcore.ConnectError("OIDC endpoint resolved to an unsafe address") from exc

        # httpcore still uses the request's original hostname for TLS SNI and
        # certificate verification; only the TCP destination is pinned here.
        return await self._network_backend.connect_tcp(
            str(addresses[0]), port, timeout, local_address, socket_options
        )

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return await self._network_backend.connect_unix_socket(path, timeout, socket_options)

    async def sleep(self, seconds):
        await self._network_backend.sleep(seconds)


class _OIDCResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self._stream = stream

    async def __aiter__(self):
        try:
            async for chunk in self._stream:
                yield chunk
        except (httpcore.NetworkError, httpcore.ProtocolError, httpcore.TimeoutException) as exc:
            raise httpx.TransportError("OIDC response could not be read safely") from exc

    async def aclose(self):
        try:
            await self._stream.aclose()
        except (httpcore.NetworkError, httpcore.ProtocolError, httpcore.TimeoutException) as exc:
            raise httpx.TransportError("OIDC response could not be closed safely") from exc


class _SafeOIDCTransport(httpx.AsyncBaseTransport):
    """HTTPX adapter over a pooled HTTPCore client with validated connections."""

    def __init__(self, *, network_backend=None, resolver=None, ssl_context=None):
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            network_backend=_SafeOIDCNetworkBackend(network_backend, resolver),
        )

    async def handle_async_request(self, request):
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = await self._pool.handle_async_request(core_request)
        except (httpcore.NetworkError, httpcore.ProtocolError, httpcore.TimeoutException) as exc:
            raise httpx.TransportError("OIDC provider connection failed safely") from exc
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_OIDCResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self):
        try:
            await self._pool.aclose()
        except (httpcore.NetworkError, httpcore.ProtocolError, httpcore.TimeoutException) as exc:
            raise httpx.TransportError("OIDC connection pool could not be closed safely") from exc


def _oidc_http_client():
    return httpx.AsyncClient(
        timeout=10.0,
        follow_redirects=False,
        transport=_SafeOIDCTransport(),
    )


def _settings():
    settings = load_settings().authentication
    required = {
        "RAGGUARD_OIDC_ISSUER": settings.oidc_issuer,
        "RAGGUARD_OIDC_CLIENT_ID": settings.oidc_client_id,
        "RAGGUARD_OIDC_REDIRECT_URI": settings.oidc_redirect_uri,
        "RAGGUARD_FRONTEND_URL": settings.frontend_url,
        "RAGGUARD_SESSION_SECRET": settings.session_secret,
    }
    if settings.oidc_token_auth_method != "none":
        required["RAGGUARD_OIDC_CLIENT_SECRET"] = settings.oidc_client_secret
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise HTTPException(status_code=503, detail="OIDC authentication is incompletely configured.")
    if settings.mode != "oidc":
        raise HTTPException(status_code=404, detail="OIDC authentication is not enabled.")
    return settings


def _require_https_endpoint(value: str) -> None:
    try:
        parsed = urlparse(value)
        port = parsed.port or 443
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(
                parsed.hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail="OIDC provider endpoint could not be resolved safely.",
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not addresses
        or any(not address.is_global for address in addresses)
    ):
        raise HTTPException(status_code=503, detail="OIDC provider metadata contains an unsafe endpoint.")


def _discovery_url(issuer: str) -> str:
    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


def _validate_token_auth_method(metadata: dict, settings) -> None:
    supported = metadata.get("token_endpoint_auth_methods_supported")
    if supported is None:
        supported = ["client_secret_basic"]
    if not isinstance(supported, list) or settings.oidc_token_auth_method not in supported:
        raise HTTPException(
            status_code=503,
            detail="The OIDC provider does not advertise the configured token authentication method.",
        )


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
    _require_https_endpoint(issuer)
    async with _oidc_http_client() as client:
        try:
            discovery_response = await client.get(_discovery_url(issuer))
            discovery_response.raise_for_status()
            metadata = discovery_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="OIDC provider discovery failed.") from exc
    if metadata.get("issuer") != issuer:
        raise HTTPException(status_code=503, detail="OIDC discovery issuer did not match configuration.")
    _require_https_endpoint(metadata.get("authorization_endpoint", ""))
    _validate_token_auth_method(metadata, settings)
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
    _require_https_endpoint(issuer)
    async with _oidc_http_client() as client:
        try:
            discovery_response = await client.get(_discovery_url(issuer))
            discovery_response.raise_for_status()
            metadata = discovery_response.json()
            if metadata.get("issuer") != issuer:
                raise ValueError("issuer mismatch")
            _validate_token_auth_method(metadata, settings)
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
            elif settings.oidc_token_auth_method == "none":
                token_form["client_id"] = settings.oidc_client_id
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
