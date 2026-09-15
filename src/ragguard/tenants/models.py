from __future__ import annotations

from dataclasses import dataclass

from ragguard.auth.tenant_context import TenantContext
from ragguard.config import LLMSettings


@dataclass(frozen=True, slots=True)
class TenantPolicy:
    tenant_id: str
    application_id: str
    environment: str
    vector_namespace: str
    policy_version: str = "v1"
    index_version: str = "v1"
    llm: LLMSettings = LLMSettings()

    def context_for(self, user_id: str | None = None, roles: tuple[str, ...] = ()) -> TenantContext:
        return TenantContext(
            tenant_id=self.tenant_id, application_id=self.application_id,
            environment=self.environment, user_id=user_id, roles=roles,
            vector_namespace=self.vector_namespace, policy_version=self.policy_version,
            index_version=self.index_version,
        )
