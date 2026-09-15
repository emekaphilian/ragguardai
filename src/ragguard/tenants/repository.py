from __future__ import annotations

from ragguard.tenants.models import TenantPolicy


class TenantRepository:
    """In-memory policy repository; replace with a durable control-plane adapter."""

    def __init__(self, policies: list[TenantPolicy]):
        self._policies = {policy.tenant_id: policy for policy in policies}

    def get(self, tenant_id: str) -> TenantPolicy | None:
        return self._policies.get(tenant_id)
