"""RAGGuard-owned tenant membership and permission resolution."""
from __future__ import annotations

from dataclasses import replace

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
        application_memberships = None
    else:
        from ragguard.api.runtime import auth_repository

        roles = auth_repository.get_membership(principal.issuer, principal.subject, tenant_id)
        if roles is None:
            raise TenantAuthorizationError("The authenticated user is not a member of this tenant.")
        if not roles:
            raise TenantAuthorizationError("The tenant membership has no granted roles.")
        # Roles come from RAGGuard's membership store, never IdP claim headers.
        if {role.lower() for role in roles} & {"admin", "owner", "workspace_admin"}:
            # These are RAGGuard tenant administrators and retain tenant-wide
            # platform access. Application administrators use explicit grants.
            application_memberships = None
        else:
            memberships = auth_repository.list_application_memberships(
                tenant_id,
                issuer=principal.issuer,
                subject=principal.subject,
            )
            application_memberships = tuple(
                (
                    membership["application_id"],
                    membership["environment"],
                    tuple(membership["roles"]),
                )
                for membership in memberships
            )

    try:
        context = TenantService(settings).resolve(
            tenant_id,
            user_id=principal.subject,
            roles=roles,
        )
        return replace(context, application_memberships=application_memberships)
    except PermissionError as exc:
        raise TenantAuthorizationError("Unknown tenant.") from exc
