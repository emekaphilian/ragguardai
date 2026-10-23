"""HTTP context construction.

Authentication integration belongs here: replace the development header parser
with verified JWT/session claims before deploying this API publicly.
"""
from __future__ import annotations

from fastapi import Request

from ragguard.auth.authorization import resolve_authorized_tenant
from ragguard.auth.principal import AuthenticationError, AuthenticationUnavailable
from ragguard.auth.providers import authenticate_principal
from ragguard.config import load_settings


def tenant_context(request: Request):
    return request.state.tenant_context


def resolve_request_context(request: Request):
    settings = load_settings()
    principal = authenticate_principal(request, settings)
    # Tenant selection is not proof of access. Non-development identities must
    # have an exact issuer/subject/tenant grant in RAGGuard's server policy.
    tenant_id = request.headers.get("X-RAGGuard-Tenant") or settings.service_auth.tenant_id
    return resolve_authorized_tenant(principal, tenant_id, settings)
