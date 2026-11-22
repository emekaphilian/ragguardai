"""HTTP context construction.

Authentication integration belongs here: replace the development header parser
with verified JWT/session claims before deploying this API publicly.
"""
from __future__ import annotations

from fastapi import Request

from ragguard.auth.authorization import resolve_authorized_tenant
from ragguard.auth.application_access import resolve_application_context
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
    context = resolve_authorized_tenant(principal, tenant_id, settings)
    from ragguard.api.runtime import application_repository

    requested_application = request.headers.get("X-RAGGuard-Application")
    requested_environment = request.headers.get("X-RAGGuard-Environment")
    grants = context.application_memberships

    if grants is None:
        if not requested_application:
            return context
        candidates = [(requested_application, requested_environment or context.environment)]
    else:
        candidates = [
            (application_id, environment)
            for application_id, environment, _ in grants
            if requested_application is None or application_id == requested_application
            if requested_environment is None or environment == requested_environment
        ]
        candidates = [
            (application_id, environment)
            for application_id, environment in candidates
            if application_repository.get(tenant_id, application_id, environment) is not None
        ]
        if not candidates:
            raise PermissionError("No authorized application is available for this tenant.")
        if requested_application is None and (context.application_id, context.environment) in candidates:
            selected_application, selected_environment = (
                context.application_id,
                context.environment,
            )
        elif len(candidates) == 1:
            selected_application, selected_environment = candidates[0]
        elif requested_application is None:
            selected_application, selected_environment = sorted(candidates)[0]
        else:
            preferred = next(
                (item for item in candidates if item[1] == context.environment),
                None,
            )
            if preferred is None:
                raise PermissionError("Select an authorized application environment.")
            selected_application, selected_environment = preferred

    if grants is None:
        selected_application, selected_environment = candidates[0]
    scoped_context, registration = resolve_application_context(
        context,
        application_repository,
        selected_application,
        selected_environment,
    )
    if registration is None or scoped_context is None:
        raise PermissionError("Application is not registered for this tenant.")
    return scoped_context
