from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .exceptions import ragguard_exception_handler
from .routes.health import router as health_router
from .routes.retrieval import router as retrieval_router
from .routes.evaluation import router as evaluation_router
from .routes.repairs import router as repairs_router
from .routes.dashboard import router as dashboard_router
from .routes.narrator import router as narrator_router

from ragguard.api.middleware import resolve_request_context
from ragguard.common.exceptions import RAGGuardError

app = FastAPI(title="RAGGuard", version="0.2.0")

app.add_exception_handler(
    RAGGuardError,
    ragguard_exception_handler,
)

app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

@app.middleware("http")
async def attach_tenant_context(request: Request, call_next):
    try:
        request.state.tenant_context = resolve_request_context(request)
    except PermissionError:
        return JSONResponse(status_code=403, content={"detail": "Unknown tenant"})
    return await call_next(request)
app.include_router(health_router, prefix="/api/v1")
app.include_router(retrieval_router, prefix="/api/v1")
app.include_router(evaluation_router, prefix="/api/v1")
app.include_router(repairs_router, prefix="/api/v1")

app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(narrator_router, prefix="/api/v1")
