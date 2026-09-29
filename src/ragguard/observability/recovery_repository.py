from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Protocol

from ragguard.observability.recovery_audit import RecoveryAuditRecord


class RecoveryAuditRepository(Protocol):
    """Repository contract for recovery audit records."""

    def save(self, record: RecoveryAuditRecord) -> RecoveryAuditRecord:
        ...

    def get(self, recovery_id: str) -> RecoveryAuditRecord | None:
        ...

    def list(
        self,
        *,
        ragguard_tenant_id: str | None = None,
        tenant_id: str | None = None,
        application_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RecoveryAuditRecord]:
        ...

    def count(
        self,
        *,
        ragguard_tenant_id: str | None = None,
        tenant_id: str | None = None,
        application_id: str | None = None,
    ) -> int:
        ...

    def delete_expired(self, before: datetime) -> int:
        ...


class InMemoryRecoveryAuditRepository(RecoveryAuditRepository):
    """Thread-safe in-process repository for local use and tests."""

    def __init__(self) -> None:
        self._records: dict[str, RecoveryAuditRecord] = {}
        self._lock = Lock()

    def save(self, record: RecoveryAuditRecord) -> RecoveryAuditRecord:
        with self._lock:
            self._records[record.recovery_id] = record
        return record

    def get(self, recovery_id: str) -> RecoveryAuditRecord | None:
        with self._lock:
            return self._records.get(recovery_id)

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

        with self._lock:
            records = list(self._records.values())

        return self._filter_and_page(
            records,
            ragguard_tenant_id=ragguard_tenant_id,
            tenant_id=tenant_id,
            application_id=application_id,
            limit=limit,
            offset=offset,
        )

    def count(
        self,
        *,
        ragguard_tenant_id: str | None = None,
        tenant_id: str | None = None,
        application_id: str | None = None,
    ) -> int:
        with self._lock:
            records = list(self._records.values())
        return len(self._filter(records, ragguard_tenant_id, tenant_id, application_id))

    def delete_expired(self, before: datetime) -> int:
        with self._lock:
            expired_ids = [
                recovery_id
                for recovery_id, record in self._records.items()
                if record.completed_at is not None
                and record.completed_at < before
                and record.final_status != "running"
            ]
            for recovery_id in expired_ids:
                del self._records[recovery_id]
        return len(expired_ids)

    @staticmethod
    def _filter(
        records: list[RecoveryAuditRecord],
        ragguard_tenant_id: str | None,
        tenant_id: str | None,
        application_id: str | None,
    ) -> list[RecoveryAuditRecord]:
        if ragguard_tenant_id is not None:
            records = [
                record
                for record in records
                if record.ragguard_tenant_id == ragguard_tenant_id
            ]
        if tenant_id is not None:
            records = [record for record in records if record.tenant_id == tenant_id]
        if application_id is not None:
            records = [
                record
                for record in records
                if record.application_id == application_id
            ]
        return records

    @classmethod
    def _filter_and_page(
        cls,
        records: list[RecoveryAuditRecord],
        *,
        ragguard_tenant_id: str | None,
        tenant_id: str | None,
        application_id: str | None,
        limit: int,
        offset: int,
    ) -> list[RecoveryAuditRecord]:
        records = cls._filter(records, ragguard_tenant_id, tenant_id, application_id)
        records.sort(key=lambda record: record.started_at, reverse=True)
        return records[offset:offset + limit]
