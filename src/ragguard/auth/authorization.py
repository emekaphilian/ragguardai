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
        from ragguard.api.runtime import auth_repository

        roles = auth_repository.get_membership(principal.issuer, principal.subject, tenant_id)
        if roles is None:
            raise TenantAuthorizationError("The authenticated user is not a member of this tenant.")
        if not roles:
            raise TenantAuthorizationError("The tenant membership has no granted roles.")
        # Roles come from RAGGuard's membership store, never IdP claim headers.

    try:
        return TenantService(settings).resolve(
            tenant_id,
            user_id=principal.subject,
            roles=roles,
        )
    except PermissionError as exc:
        raise TenantAuthorizationError("Unknown tenant.") from exc
