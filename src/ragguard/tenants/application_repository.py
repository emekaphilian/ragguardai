from __future__ import annotations

from typing import Protocol

from ragguard.tenants.application_registration import ApplicationRegistration
from ragguard.tenants.models import TenantPolicy


class ApplicationRepository(Protocol):
    def upsert(self, application: ApplicationRegistration) -> ApplicationRegistration:
        ...

    def get(
        self,
        ragguard_tenant_id: str,
        application_id: str,
        environment: str,
        *,
        active_only: bool = True,
    ) -> ApplicationRegistration | None:
        ...

    def list(
        self,
        ragguard_tenant_id: str,
        *,
        active_only: bool = True,
    ) -> list[ApplicationRegistration]:
        ...

    def find_for_observation(
        self,
        application_id: str,
        environment: str,
    ) -> list[ApplicationRegistration]:
        ...

    def bootstrap(self, policies: tuple[TenantPolicy, ...]) -> int:
        ...