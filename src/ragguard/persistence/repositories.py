from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ragguard.observability.recovery_audit import (
    RecoveryAuditRecord,
    record_from_dict,
)
from ragguard.observability.recovery_repository import RecoveryAuditRepository
from ragguard.observability.recovery_repository import InMemoryRecoveryAuditRepository

from .database import connect
from .models import RecoveryAuditRow


class PostgreSQLRecoveryAuditRepository(RecoveryAuditRepository):
    """PostgreSQL-backed audit repository with no graph-layer dependencies."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        connection_factory: Callable | None = None,
    ) -> None:
        self._database_url = database_url
        self._connection_factory = connection_factory

    def _connect(self):
        if self._connection_factory is not None:
            return self._connection_factory()
        return connect(self._database_url)

    def save(self, record: RecoveryAuditRecord) -> RecoveryAuditRecord:
        row = RecoveryAuditRow.from_record(record)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO recovery_audits (
                        recovery_id, ragguard_tenant_id, external_tenant_id,
                        application_id, started_at, final_status, record
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (recovery_id) DO UPDATE SET
                        ragguard_tenant_id = EXCLUDED.ragguard_tenant_id,
                        external_tenant_id = EXCLUDED.external_tenant_id,
                        application_id = EXCLUDED.application_id,
                        started_at = EXCLUDED.started_at,
                        final_status = EXCLUDED.final_status,
                        record = EXCLUDED.record
                    """,
                    (
                        row.recovery_id,
                        row.ragguard_tenant_id,
                        row.tenant_id,
                        row.application_id,
                        row.started_at,
                        row.final_status,
                        json.dumps(row.document),
                    ),
                )
        return record

    def get(self, recovery_id: str) -> RecoveryAuditRecord | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT record FROM recovery_audits WHERE recovery_id = %s",
                    (recovery_id,),
                )
                result = cursor.fetchone()

        return self._decode(result[0]) if result else None

    def list(
        self,
        *,
        ragguard_tenant_id: str | None = None,
        tenant_id: str | None = None,
        application_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RecoveryAuditRecord]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        where_clause, parameters = self._where_clause(
            ragguard_tenant_id,
            tenant_id,
            application_id,
        )
        parameters.extend((limit, offset))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT record FROM recovery_audits {where_clause} "
                    "ORDER BY started_at DESC LIMIT %s OFFSET %s",
                    tuple(parameters),
                )
                results = cursor.fetchall()

        return [self._decode(row[0]) for row in results]

    def count(
        self,
        *,
        ragguard_tenant_id: str | None = None,
        tenant_id: str | None = None,
        application_id: str | None = None,
    ) -> int:
        where_clause, parameters = self._where_clause(
            ragguard_tenant_id,
            tenant_id,
            application_id,
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM recovery_audits {where_clause}",
                    tuple(parameters),
                )
                result = cursor.fetchone()
        return int(result[0])

    def delete_expired(self, before: datetime) -> int:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM recovery_audits
                    WHERE final_status <> 'running'
                      AND record->>'completed_at' IS NOT NULL
                      AND (record->>'completed_at')::timestamptz < %s
                    RETURNING recovery_id
                    """,
                    (before,),
                )
                return len(cursor.fetchall())

    @staticmethod
    def _where_clause(
        ragguard_tenant_id: str | None,
        tenant_id: str | None,
        application_id: str | None,
    ) -> tuple[str, list[Any]]:
        filters = []
        parameters: list[Any] = []
        for column, value in (
            ("ragguard_tenant_id", ragguard_tenant_id),
            ("external_tenant_id", tenant_id),
            ("application_id", application_id),
        ):
            if value is not None:
                filters.append(f"{column} = %s")
                parameters.append(value)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        return where_clause, parameters

    @staticmethod
    def _decode(value: dict[str, Any] | str) -> RecoveryAuditRecord:
        document = json.loads(value) if isinstance(value, str) else value
        return record_from_dict(document)


def create_recovery_audit_repository(
    *,
    backend: str | None = None,
    database_url: str | None = None,
) -> RecoveryAuditRepository:
    selected_backend = (backend or os.getenv("RAGGUARD_AUDIT_BACKEND", "memory"))
    selected_backend = selected_backend.strip().lower()

    if selected_backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryRecoveryAuditRepository()
    if selected_backend in {"postgres", "postgresql"}:
        dsn = database_url or os.getenv("RAGGUARD_DATABASE_URL")
        if not dsn:
            raise ValueError(
                "RAGGUARD_DATABASE_URL is required when PostgreSQL audit storage is enabled."
            )
        return PostgreSQLRecoveryAuditRepository(dsn)

    raise ValueError(f"Unsupported recovery audit backend: {selected_backend}")
