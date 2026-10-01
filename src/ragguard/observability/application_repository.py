from __future__ import annotations

from threading import Lock

from ragguard.tenants.application_registration import ApplicationRegistration
from ragguard.tenants.application_repository import ApplicationRepository
from ragguard.tenants.models import TenantPolicy


class InMemoryApplicationRepository(ApplicationRepository):
    """In-process application registry for local development and tests."""

    def __init__(self) -> None:
        self._applications: dict[tuple[str, str, str], ApplicationRegistration] = {}
        self._lock = Lock()

    def upsert(self, application: ApplicationRegistration) -> ApplicationRegistration:
        key = self._key(application)
        with self._lock:
            self._applications[key] = application
        return application

    def get(
        self,
        ragguard_tenant_id: str,
        application_id: str,
        environment: str,
        *,
        active_only: bool = True,
    ) -> ApplicationRegistration | None:
        with self._lock:
            application = self._applications.get(
                (ragguard_tenant_id, application_id, environment)
            )
        if application is not None and active_only and not application.active:
            return None
        return application

    def list(
        self,
        ragguard_tenant_id: str,
        *,
        active_only: bool = True,
    ) -> list[ApplicationRegistration]:
        with self._lock:
            applications = [
                application
                for application in self._applications.values()
                if application.ragguard_tenant_id == ragguard_tenant_id
                and (application.active or not active_only)
            ]
        return sorted(
            applications,
            key=lambda application: (
                application.display_name.lower(),
                application.environment.lower(),
            ),
        )

    def find_for_observation(
        self,
        application_id: str,
        environment: str,
    ) -> list[ApplicationRegistration]:
        with self._lock:
            return [
                application
                for application in self._applications.values()
                if application.active
                and application.application_id == application_id
                and application.environment == environment
                and application.observation_token_env_var
            ]

    def bootstrap(self, policies: tuple[TenantPolicy, ...]) -> int:
        inserted = 0
        with self._lock:
            for policy in policies:
                key = (
                    policy.tenant_id,
                    policy.application_id,
                    policy.environment,
                )
                if key in self._applications:
                    continue
                self._applications[key] = ApplicationRegistration(
                    ragguard_tenant_id=policy.tenant_id,
                    application_id=policy.application_id,
                    display_name=policy.application_id,
                    environment=policy.environment,
                    knowledge_source="managed_index",
                    vector_namespace=policy.vector_namespace,
                )
                inserted += 1
        return inserted

    @staticmethod
    def _key(application: ApplicationRegistration) -> tuple[str, str, str]:
        return (
            application.ragguard_tenant_id,
            application.application_id,
            application.environment,
        )