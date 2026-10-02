from __future__ import annotations

import os
from dataclasses import dataclass, replace
from hmac import compare_digest

from ragguard.auth.tenant_context import TenantContext
from ragguard.config import Settings
from ragguard.tenants.application_registration import ApplicationRegistration
from ragguard.tenants.application_repository import ApplicationRepository
from ragguard.tenants.service import TenantService


class ServiceAuthenticationError(PermissionError):
    """Raised when service-to-service authentication fails."""


@dataclass(frozen=True, slots=True)
class AuthenticatedService:
    application_id: str
    tenant_context: TenantContext
    registration: ApplicationRegistration | None = None


def authenticate_service(
    authorization: str | None,
    settings: Settings,
    *,
    application_id: str | None = None,
    environment: str | None = None,
    application_repository: ApplicationRepository | None = None,
) -> AuthenticatedService:
    """Authenticate a legacy shared service token or a registered app token."""
    if not authorization:
        raise ServiceAuthenticationError(
            "Missing Authorization header."
        )

    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token:
        raise ServiceAuthenticationError(
            "Invalid Authorization header."
        )

    configured_token = settings.service_auth.token
    if configured_token and compare_digest(token, configured_token):
        tenant_context = TenantService(settings).resolve(
            settings.service_auth.tenant_id,
        )
        if tenant_context.application_id != settings.service_auth.application:
            raise ServiceAuthenticationError(
                "Service application is not authorized for this tenant."
            )
        return AuthenticatedService(
            application_id=settings.service_auth.application,
            tenant_context=tenant_context,
        )

    if application_repository is not None and application_id and environment:
        for registration in application_repository.find_for_observation(
            application_id,
            environment,
        ):
            token_env_var = registration.observation_token_env_var
            registered_token = os.getenv(token_env_var) if token_env_var else None
            if not registered_token or not compare_digest(token, registered_token):
                continue
            tenant_context = TenantService(settings).resolve(
                registration.ragguard_tenant_id,
            )
            tenant_context = replace(
                tenant_context,
                application_id=registration.application_id,
                environment=registration.environment,
                vector_namespace=(
                    registration.vector_namespace or tenant_context.vector_namespace
                ),
            )
            return AuthenticatedService(
                application_id=registration.application_id,
                tenant_context=tenant_context,
                registration=registration,
            )

    if not configured_token and application_repository is None:
        raise ServiceAuthenticationError("Service authentication is not configured.")
    raise ServiceAuthenticationError("Invalid service credential.")
