"""RAGGuard-owned tenant membership and permission resolution."""
from __future__ import annotations

from ragguard.auth.tenant_context import TenantContext
from ragguard.config import Settings
from ragguard.tenants.service import TenantService

from .principal import TenantAuthorizationError, VerifiedPrincipal


def resolve_authorized_tenant(
    principal: VerifiedPrincipal,
    tenant_id: str,
    settings: Settings,
) -> TenantContext:
    """Build tenant context only after checking server-side membership."""
    if principal.authentication_method == "development_headers":
        if settings.authentication.mode != "development_headers":
            raise TenantAuthorizationError("Development identity is not authorized.")
        roles = principal.roles
    else:
        membership = next((
            item for item in settings.authentication.tenant_memberships
            if item.issuer == principal.issuer
            and item.subject == principal.subject
            and item.tenant_id == tenant_id
        ), None)
        if membership is None:
            raise TenantAuthorizationError("The authenticated user is not a member of this tenant.")
        # Roles are issued by RAGGuard membership policy, not accepted directly
        # from identity-provider or proxy role headers.
        roles = membership.roles

    try:
        return TenantService(settings).resolve(
            tenant_id,
            user_id=principal.subject,
            roles=roles,
        )
    except PermissionError as exc:
        raise TenantAuthorizationError("Unknown tenant.") from exc
