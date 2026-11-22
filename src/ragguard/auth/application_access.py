"""Application-level access checks for RAGGuard workspace users."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from ragguard.auth.tenant_context import TenantContext
from ragguard.tenants.application_registration import ApplicationRegistration


def application_is_allowed(
    context: TenantContext,
    application_id: str,
    environment: str | None = None,
) -> bool:
    """Return whether this user may inspect an app/environment in the tenant."""
    grants = context.application_memberships
    if grants is None:
        return True
    return any(
        granted_app == application_id
        and (environment is None or granted_environment == environment)
        for granted_app, granted_environment, _ in grants
    )


def visible_applications(
    context: TenantContext,
    applications: Iterable[ApplicationRegistration],
) -> list[ApplicationRegistration]:
    if context.application_memberships is None:
        return list(applications)
    return [
        application
        for application in applications
        if application_is_allowed(
            context,
            application.application_id,
            application.environment,
        )
    ]


def application_roles(
    context: TenantContext,
    application_id: str,
    environment: str,
) -> tuple[str, ...]:
    grants = context.application_memberships
    if grants is None:
        return ("admin", "operator", "reader")
    return next((roles for app, env, roles in grants if app == application_id and env == environment), ())


def resolve_application_context(context: TenantContext, application_repository, application_id: str, environment: str):
    """Resolve one registered application under the caller's exact membership."""
    if not application_is_allowed(context, application_id, environment):
        return None, None
    registration = application_repository.get(context.tenant_id, application_id, environment)
    if registration is None:
        return None, None
    scoped = replace(
        context,
        application_id=registration.application_id,
        environment=registration.environment,
        vector_namespace=registration.vector_namespace or context.vector_namespace,
    )
    return scoped, registration


def require_application_role(context: TenantContext, application_id: str, environment: str, allowed_roles: set[str]) -> bool:
    """Check tenant-wide or exact application grant against the selected scope."""
    tenant_roles = {str(role).lower() for role in context.roles}
    if tenant_roles & {"operator", "admin", "owner", "workspace_admin"}:
        return True
    return bool({role.lower() for role in application_roles(context, application_id, environment)} & allowed_roles)
