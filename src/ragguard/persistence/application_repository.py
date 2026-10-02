from __future__ import annotations

import os
from typing import Any

from ragguard.observability.application_repository import InMemoryApplicationRepository
from ragguard.tenants.application_registration import ApplicationRegistration
from ragguard.tenants.application_repository import ApplicationRepository
from ragguard.tenants.models import TenantPolicy

from .database import connect, selected_persistence_backend


class PostgreSQLApplicationRepository(ApplicationRepository):
    """PostgreSQL source of truth for registered RAG applications."""

    def __init__(self, database_url: str | None = None, *, connection_factory=None):
        self._database_url = database_url
        self._connection_factory = connection_factory

    def _connect(self):
        return (
            self._connection_factory()
            if self._connection_factory is not None
            else connect(self._database_url)
        )

    def upsert(self, application: ApplicationRegistration) -> ApplicationRegistration:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO registered_applications (
                        ragguard_tenant_id, application_id, display_name,
                        environment, knowledge_source, vector_namespace,
                        query_endpoint_url, query_token_env_var,
                        observation_token_env_var, active, repair_authorized
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ragguard_tenant_id, application_id, environment)
                    DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        knowledge_source = EXCLUDED.knowledge_source,
                        vector_namespace = EXCLUDED.vector_namespace,
                        query_endpoint_url = EXCLUDED.query_endpoint_url,
                        query_token_env_var = EXCLUDED.query_token_env_var,
                        observation_token_env_var = EXCLUDED.observation_token_env_var,
                        active = EXCLUDED.active,
                        repair_authorized = EXCLUDED.repair_authorized,
                        updated_at = now()
                    """,
                    self._parameters(application),
                )
        return application

    def get(
        self,
        ragguard_tenant_id: str,
        application_id: str,
        environment: str,
        *,
        active_only: bool = True,
    ) -> ApplicationRegistration | None:
        where = "ragguard_tenant_id = %s AND application_id = %s AND environment = %s"
        parameters: list[Any] = [ragguard_tenant_id, application_id, environment]
        if active_only:
            where += " AND active"
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._columns()} FROM registered_applications WHERE {where}",
                    tuple(parameters),
                )
                row = cursor.fetchone()
        return self._decode(row) if row else None

    def list(
        self,
        ragguard_tenant_id: str,
        *,
        active_only: bool = True,
    ) -> list[ApplicationRegistration]:
        where = "ragguard_tenant_id = %s"
        parameters: list[Any] = [ragguard_tenant_id]
        if active_only:
            where += " AND active"
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._columns()} FROM registered_applications "
                    f"WHERE {where} ORDER BY display_name, environment",
                    tuple(parameters),
                )
                rows = cursor.fetchall()
        return [self._decode(row) for row in rows]

    def find_for_observation(
        self,
        application_id: str,
        environment: str,
    ) -> list[ApplicationRegistration]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._columns()} FROM registered_applications "
                    "WHERE application_id = %s AND environment = %s "
                    "AND active AND observation_token_env_var IS NOT NULL",
                    (application_id, environment),
                )
                rows = cursor.fetchall()
        return [self._decode(row) for row in rows]

    def bootstrap(self, policies: tuple[TenantPolicy, ...]) -> int:
        inserted = 0
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for policy in policies:
                    cursor.execute(
                        """
                        INSERT INTO registered_applications (
                            ragguard_tenant_id, application_id, display_name,
                            environment, knowledge_source, vector_namespace, active
                        ) VALUES (%s, %s, %s, %s, 'managed_index', %s, TRUE)
                        ON CONFLICT (ragguard_tenant_id, application_id, environment)
                        DO NOTHING
                        RETURNING application_id
                        """,
                        (
                            policy.tenant_id,
                            policy.application_id,
                            policy.application_id,
                            policy.environment,
                            policy.vector_namespace,
                        ),
                    )
                    if cursor.fetchone() is not None:
                        inserted += 1
        return inserted

    @staticmethod
    def _columns() -> str:
        return (
            "ragguard_tenant_id, application_id, display_name, environment, "
            "knowledge_source, vector_namespace, query_endpoint_url, "
            "query_token_env_var, observation_token_env_var, active, "
            "repair_authorized"
        )

    @staticmethod
    def _parameters(application: ApplicationRegistration) -> tuple[Any, ...]:
        return (
            application.ragguard_tenant_id,
            application.application_id,
            application.display_name,
            application.environment,
            application.knowledge_source,
            application.vector_namespace,
            application.query_endpoint_url,
            application.query_token_env_var,
            application.observation_token_env_var,
            application.active,
            application.repair_authorized,
        )

    @staticmethod
    def _decode(row: tuple[Any, ...]) -> ApplicationRegistration:
        return ApplicationRegistration(
            ragguard_tenant_id=row[0],
            application_id=row[1],
            display_name=row[2],
            environment=row[3],
            knowledge_source=row[4],
            vector_namespace=row[5],
            query_endpoint_url=row[6],
            query_token_env_var=row[7],
            observation_token_env_var=row[8],
            active=row[9],
            repair_authorized=row[10],
        )


def create_application_repository(
    *,
    backend: str | None = None,
    database_url: str | None = None,
) -> ApplicationRepository:
    selected_backend = selected_persistence_backend(backend)
    if selected_backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryApplicationRepository()
    if selected_backend in {"postgres", "postgresql"}:
        dsn = database_url or os.getenv("RAGGUARD_DATABASE_URL")
        if not dsn:
            raise ValueError(
                "RAGGUARD_DATABASE_URL is required when PostgreSQL application "
                "storage is enabled."
            )
        return PostgreSQLApplicationRepository(dsn)
    raise ValueError(f"Unsupported application registry backend: {selected_backend}")