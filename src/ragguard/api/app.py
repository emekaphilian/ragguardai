from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .exceptions import ragguard_exception_handler
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
from .recovery_routes import build_recovery_router

from ragguard.api.middleware import resolve_request_context
from ragguard.api.runtime import application_repository
from ragguard.common.exceptions import RAGGuardError
from ragguard.config import load_settings
from ragguard.persistence.database import apply_migrations, selected_persistence_backend


@asynccontextmanager
async def lifespan(_: FastAPI):
    if selected_persistence_backend() in {"postgres", "postgresql"}:
        apply_migrations()
    application_repository.bootstrap(load_settings().tenant_policies)
    yield


app = FastAPI(title="RAGGuard", version="0.2.0", lifespan=lifespan)

app.add_exception_handler(
    RAGGuardError,
    ragguard_exception_handler,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_tenant_context(request: Request, call_next):
    # External telemetry identifies its source in the observation contract;
    # it is independent of RAGGuard's internal workspace tenant context.
    if request.url.path == "/api/v1/observations" or request.url.path.startswith("/api/v1/admin/"):
        return await call_next(request)

    try:
        request.state.tenant_context = resolve_request_context(request)
    except PermissionError:
        return JSONResponse(
            status_code=403,
            content={"detail": "Unknown tenant"},
        )

    return await call_next(request)


app.include_router(health_router, prefix="/api/v1")
app.include_router(applications_router, prefix="/api/v1")
app.include_router(retrieval_router, prefix="/api/v1")
app.include_router(evaluation_router, prefix="/api/v1")
app.include_router(repairs_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(narrator_router, prefix="/api/v1")
app.include_router(observations_router, prefix="/api/v1")
app.include_router(build_recovery_router(recovery_repository))
app.include_router(replay_router)
app.include_router(admin_router, prefix="/api/v1")
