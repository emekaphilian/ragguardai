from __future__ import annotations

from dataclasses import dataclass

from ragguard.auth.tenant_context import TenantContext
from ragguard.config import Settings
from ragguard.tenants.service import TenantService


class ServiceAuthenticationError(PermissionError):
    """Raised when service-to-service authentication fails."""


@dataclass(frozen=True, slots=True)
class AuthenticatedService:
    application_id: str
    tenant_context: TenantContext


def authenticate_service(
    authorization: str | None,
    settings: Settings,
) -> AuthenticatedService:
    """Authenticate a trusted service using a configured bearer token."""

    configured_token = settings.service_auth.token

    if not configured_token:
        raise ServiceAuthenticationError(
            "Service authentication is not configured."
        )

    if not authorization:
        raise ServiceAuthenticationError(
            "Missing Authorization header."
        )

    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token:
        raise ServiceAuthenticationError(
            "Invalid Authorization header."
        )

    if token != configured_token:
        raise ServiceAuthenticationError(
            "Invalid service credential."
        )

    application_id = settings.service_auth.application
    tenant_id = settings.service_auth.tenant_id

    tenant_context = TenantService(settings).resolve(
        tenant_id=tenant_id,
    )

    if tenant_context.application_id != application_id:
        raise ServiceAuthenticationError(
            "Service application is not authorized for this tenant."
        )

    return AuthenticatedService(
        application_id=application_id,
        tenant_context=tenant_context,
    )
