from __future__ import annotations

from ragguard.auth.tenant_context import TenantContext
from ragguard.config import Settings
from ragguard.tenants.models import TenantPolicy
from ragguard.tenants.repository import TenantRepository


class TenantService:
    def __init__(self, settings: Settings):
        policies = settings.tenant_policies or (TenantPolicy(
            tenant_id="development", application_id="ragguard", environment=settings.environment,
            vector_namespace="development", llm=settings.llm,
        ),)
        self.repository = TenantRepository(list(policies))

    def resolve(self, tenant_id: str, user_id: str | None = None, roles: tuple[str, ...] = ()) -> TenantContext:
        policy = self.repository.get(tenant_id)
        if policy is None:
            raise PermissionError("Unknown tenant")
        return policy.context_for(user_id=user_id, roles=roles)

    def llm_settings_for(self, context: TenantContext):
        policy = self.repository.get(context.tenant_id)
        if policy is None or policy.application_id != context.application_id:
            raise PermissionError("Tenant context is not recognized")
        return policy.llm
