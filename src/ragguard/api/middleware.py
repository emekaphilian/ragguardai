"""HTTP context construction.

Authentication integration belongs here: replace the development header parser
with verified JWT/session claims before deploying this API publicly.
"""
from __future__ import annotations

from fastapi import Request

from ragguard.config import load_settings
from ragguard.tenants.service import TenantService


def tenant_context(request: Request):
    return request.state.tenant_context


def resolve_request_context(request: Request):
    # This is a local-development transport only. The service still performs
    # policy lookup and never treats the caller supplied id as a complete context.
    settings = load_settings()
    # When no workspace tenant is explicitly selected, use the same internal
    # tenant as service-authenticated observations. This keeps the default
    # Control Center view aligned with the observation writer.
    tenant_id = request.headers.get("X-RAGGuard-Tenant") or settings.service_auth.tenant_id
    user_id = request.headers.get("X-RAGGuard-User")
    roles = tuple(role.strip() for role in request.headers.get("X-RAGGuard-Roles", "").split(",") if role.strip())
    return TenantService(settings).resolve(tenant_id, user_id=user_id, roles=roles)
