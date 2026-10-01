from __future__ import annotations

import json
import os
from typing import Any

from ragguard.observability.observation_activity import ObservationRecord
from ragguard.observability.observation_repository import (
    InMemoryObservationRepository,
    ObservationRepository,
)

from .database import connect, selected_persistence_backend


class PostgreSQLObservationRepository(ObservationRepository):
    """PostgreSQL-backed observation history with indexed filter columns."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        connection_factory=None,
    ) -> None:
        self._database_url = database_url
        self._connection_factory = connection_factory

    def _connect(self):
        if self._connection_factory is not None:
            return self._connection_factory()
        return connect(self._database_url)

    def save(self, record: ObservationRecord) -> ObservationRecord:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO observations (
                        observation_id, ragguard_tenant_id, application_id,
                        created_at, status, query, evaluation,
                        observation, failure, recovery
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb
                    )
                    ON CONFLICT (observation_id) DO UPDATE SET
                        ragguard_tenant_id = EXCLUDED.ragguard_tenant_id,
                        application_id = EXCLUDED.application_id,
                        created_at = EXCLUDED.created_at,
                        status = EXCLUDED.status,
                        query = EXCLUDED.query,
                        evaluation = EXCLUDED.evaluation,
                        observation = EXCLUDED.observation,
                        failure = EXCLUDED.failure,
                        recovery = EXCLUDED.recovery
                    """,
                    (
                        record.observation_id,
                        record.ragguard_tenant_id,
                        record.application_id,
                        record.created_at,
                        record.status,
                        record.query,
                        json.dumps(record.evaluation),
                        json.dumps(record.observation),
                        json.dumps(record.failure),
                        json.dumps(record.recovery),
                    ),
                )
        return record

    def clear(self) -> int:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM observations RETURNING observation_id")
                return len(cursor.fetchall())

    def get(self, observation_id: str) -> ObservationRecord | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT observation_id, ragguard_tenant_id, "
                    "application_id, created_at, status, query, evaluation, "
                    "observation, failure, recovery FROM observations "
                    "WHERE observation_id = %s",
                    (observation_id,),
                )
                result = cursor.fetchone()
        return self._decode(result) if result else None

    def list(
        self,
        *,
        ragguard_tenant_id: str | None = None,
        application_id: str | None = None,
        status: str | None = None,
        failure_detected: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ObservationRecord]:
        self._validate_page(limit, offset)
        where_clause, parameters = self._where_clause(
            ragguard_tenant_id,
            application_id,
            status,
            failure_detected,
        )
        parameters.extend((limit, offset))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT observation_id, ragguard_tenant_id, "
                    "application_id, created_at, status, query, evaluation, "
                    "observation, failure, recovery FROM observations "
                    f"{where_clause} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    tuple(parameters),
                )
                results = cursor.fetchall()
        return [self._decode(row) for row in results]

    def count(
        self,
        *,
        ragguard_tenant_id: str | None = None,
        application_id: str | None = None,
        status: str | None = None,
        failure_detected: bool | None = None,
    ) -> int:
        where_clause, parameters = self._where_clause(
            ragguard_tenant_id,
            application_id,
            status,
            failure_detected,
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM observations {where_clause}",
                    tuple(parameters),
                )
                result = cursor.fetchone()
        return int(result[0])

    @staticmethod
    def _validate_page(limit: int, offset: int) -> None:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

    @staticmethod
    def _where_clause(
        ragguard_tenant_id: str | None,
        application_id: str | None,
        status: str | None,
        failure_detected: bool | None,
    ) -> tuple[str, list[Any]]:
        filters = []
        parameters: list[Any] = []
        for column, value in (
            ("ragguard_tenant_id", ragguard_tenant_id),
            ("application_id", application_id),
            ("status", status),
        ):
            if value is not None:
                filters.append(f"{column} = %s")
                parameters.append(value)
        if failure_detected is True:
            filters.append("failure IS NOT NULL")
        elif failure_detected is False:
            filters.append("failure IS NULL")
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        return where_clause, parameters

    @staticmethod
    def _decode(row: tuple[Any, ...]) -> ObservationRecord:
        values = list(row)
        for index in range(6, 10):
            if isinstance(values[index], str):
                values[index] = json.loads(values[index])
        return ObservationRecord(*values)


def create_observation_repository(
    *,
    backend: str | None = None,
    database_url: str | None = None,
) -> ObservationRepository:
    selected_backend = selected_persistence_backend(backend)
    if selected_backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryObservationRepository()
    if selected_backend in {"postgres", "postgresql"}:
        dsn = database_url or os.getenv("RAGGUARD_DATABASE_URL")
        if not dsn:
            raise ValueError(
                "RAGGUARD_DATABASE_URL is required when PostgreSQL observation "
                "storage is enabled."
            )
        return PostgreSQLObservationRepository(dsn)
    raise ValueError(f"Unsupported observation storage backend: {selected_backend}")
