from contextlib import asynccontextmanager
import hashlib
import os
import hmac

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .exceptions import ragguard_exception_handler
from ragguard.auth.principal import AuthenticationError, AuthenticationUnavailable
from .routes.health import router as health_router
from .routes.applications import router as applications_router
from .routes.retrieval import router as retrieval_router
from .routes.evaluation import router as evaluation_router
from .routes.repairs import router as repairs_router
from .routes.dashboard import router as dashboard_router
from .routes.narrator import router as narrator_router
from .routes.observations import router as observations_router
from .routes.observations import recovery_repository
from .routes.replay import router as replay_router
from .routes.admin import router as admin_router
from .routes.integration import router as integration_router
from ragguard.auth.oidc import router as auth_router
from .recovery_routes import build_recovery_router

from ragguard.api.middleware import resolve_request_context
from ragguard.auth.application_access import require_application_role
from ragguard.api.runtime import application_repository
from ragguard.api.runtime import auth_repository
from ragguard.common.exceptions import RAGGuardError
from ragguard.config import load_settings
from ragguard.persistence.database import apply_migrations, selected_persistence_backend


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = load_settings()
    backend = selected_persistence_backend()
    if settings.authentication.mode == "oidc":
        auth = settings.authentication
        required = (
            auth.oidc_issuer,
            auth.oidc_client_id,
            auth.oidc_redirect_uri,
            auth.frontend_url,
            auth.session_secret,
        )
        if auth.oidc_token_auth_method != "none":
            required += (auth.oidc_client_secret,)
        if any(not value for value in required):
            raise RuntimeError("OIDC mode requires issuer, client ID, redirect URI, frontend URL, and session secret.")
        if len(auth.session_secret or "") < 32:
            raise RuntimeError("RAGGUARD_SESSION_SECRET must contain at least 32 characters.")
        if backend not in {"postgres", "postgresql"}:
            raise RuntimeError("OIDC mode requires PostgreSQL-backed sessions and tenant memberships.")
        if not auth.oidc_issuer.startswith("https://") or not auth.oidc_redirect_uri.startswith("https://"):
            raise RuntimeError("Production OIDC issuer and redirect URI must use HTTPS.")
        from urllib.parse import urlparse
        frontend = urlparse(auth.frontend_url)
        if frontend.scheme != "https" or not frontend.netloc or frontend.path not in {"", "/"}:
            raise RuntimeError("RAGGUARD_FRONTEND_URL must be an HTTPS origin without a path.")
        if auth.session_cookie_samesite == "none" and not auth.session_cookie_secure:
            raise RuntimeError("Cross-site OIDC cookies require Secure.")
        bootstrap_subject = os.getenv("RAGGUARD_OIDC_BOOTSTRAP_ADMIN_SUBJECT", "").strip()
        bootstrap_tenant = os.getenv("RAGGUARD_OIDC_BOOTSTRAP_ADMIN_TENANT", "").strip()
        if not bootstrap_subject or not bootstrap_tenant:
            raise RuntimeError("Set the initial OIDC administrator subject and tenant before enabling OIDC.")
    if backend in {"postgres", "postgresql"}:
        apply_migrations()
    elif settings.environment.lower() in {"production", "staging"}:
        raise RuntimeError("Staging and production require PostgreSQL-backed managed document storage and workspace activity.")
    application_repository.bootstrap(settings.tenant_policies)
    from ragguard.api.runtime import workspace
    workspace.refresh()
    if settings.authentication.mode == "oidc":
        issuer = settings.authentication.oidc_issuer
        subject = os.environ["RAGGUARD_OIDC_BOOTSTRAP_ADMIN_SUBJECT"].strip()
        tenant = os.environ["RAGGUARD_OIDC_BOOTSTRAP_ADMIN_TENANT"].strip()
        auth_repository.bootstrap_admin_once(issuer, subject, tenant)
    yield


app = FastAPI(title="RAGGuard", version="0.2.0", lifespan=lifespan)

app.add_exception_handler(
    RAGGuardError,
    ragguard_exception_handler,
)

_app_settings = load_settings()
_auth_settings = _app_settings.authentication
_development_origins = [] if (
    _auth_settings.mode == "oidc" or _app_settings.environment.lower() == "production"
) else [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([
        *_development_origins,
        *_auth_settings.frontend_origins,
        *([_auth_settings.frontend_url.rstrip("/")] if _auth_settings.frontend_url else []),
    ])),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_tenant_context(request: Request, call_next):
    # External telemetry identifies its source in the observation contract;
    # it is independent of RAGGuard's internal workspace tenant context.
    settings = load_settings()
    if (
        settings.authentication.mode == "oidc"
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.url.path not in {"/api/v1/observations", "/api/v1/auth/callback"}
    ):
        session_id = request.cookies.get(settings.authentication.session_cookie_name)
        if session_id:
            session = auth_repository.get_session(session_id)
            supplied = request.headers.get("X-CSRF-Token", "")
            supplied_hash = hashlib.sha256(supplied.encode()).hexdigest()
            if not session or not supplied or not hmac.compare_digest(session.get("csrf_hash", ""), supplied_hash):
                return JSONResponse(status_code=403, content={"detail": "CSRF verification failed."})

    if (
        request.url.path == "/api/v1/health"
        or request.url.path == "/api/v1/observations"
        or request.url.path.startswith("/api/v1/admin/")
        or request.url.path.startswith("/api/v1/auth/")
    ):
        return await call_next(request)

    try:
        request.state.tenant_context = resolve_request_context(request)
    except AuthenticationError as exc:
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
        )
    except AuthenticationUnavailable as exc:
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc)},
        )
    except PermissionError:
        return JSONResponse(
            status_code=403,
            content={"detail": "Unknown tenant"},
        )

    context = request.state.tenant_context
    if settings.authentication.mode == "oidc" and request.method not in {"GET", "HEAD", "OPTIONS"}:
        # Repair accepts an application override in its body. Its route resolves
        # and authorizes that exact target, so middleware must not authorize it
        # against a potentially different header-selected application.
        if request.url.path == "/api/v1/query":
            return await call_next(request)
        if request.url.path == "/api/v1/repair":
            tenant_roles = {str(role).lower() for role in context.roles}
            if not tenant_roles & {"operator", "admin", "owner", "workspace_admin"}:
                return JSONResponse(status_code=403, content={"detail": "Repair requires a RAGGuard tenant operator."})
            return await call_next(request)
        if not require_application_role(
            context, context.application_id, context.environment, {"operator", "admin"}
        ):
            return JSONResponse(status_code=403, content={"detail": "This tenant or application role cannot modify workspace data."})

    return await call_next(request)


app.include_router(health_router, prefix="/api/v1")
app.include_router(applications_router, prefix="/api/v1")
app.include_router(retrieval_router, prefix="/api/v1")
app.include_router(evaluation_router, prefix="/api/v1")
app.include_router(repairs_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(narrator_router, prefix="/api/v1")
app.include_router(observations_router, prefix="/api/v1")
app.include_router(integration_router, prefix="/api/v1")
app.include_router(build_recovery_router(recovery_repository))
app.include_router(replay_router)
app.include_router(admin_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
