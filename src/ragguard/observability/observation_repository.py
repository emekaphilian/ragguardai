from __future__ import annotations

from threading import Lock
from typing import Protocol

from ragguard.observability.observation_activity import ObservationRecord


class ObservationRepository(Protocol):
    """Repository contract for evaluated observation history."""

    def save(self, record: ObservationRecord) -> ObservationRecord:
        ...

    def clear(self) -> int:
        """Delete all observations and return the number removed."""
        ...

    def get(self, observation_id: str) -> ObservationRecord | None:
        ...

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
        ...

    def count(
        self,
        *,
        ragguard_tenant_id: str | None = None,
        application_id: str | None = None,
        status: str | None = None,
        failure_detected: bool | None = None,
    ) -> int:
        ...


class InMemoryObservationRepository:
    """Thread-safe observation repository for local use and tests."""

    def __init__(self) -> None:
        self._records: dict[str, ObservationRecord] = {}
        self._lock = Lock()

    def save(self, record: ObservationRecord) -> ObservationRecord:
        with self._lock:
            self._records[record.observation_id] = record
        return record

    def clear(self) -> int:
        with self._lock:
            count = len(self._records)
            self._records.clear()
        return count

    def get(self, observation_id: str) -> ObservationRecord | None:
        with self._lock:
            return self._records.get(observation_id)

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
        with self._lock:
            records = list(self._records.values())
        records = self._filter(
            records,
            ragguard_tenant_id=ragguard_tenant_id,
            application_id=application_id,
            status=status,
            failure_detected=failure_detected,
        )
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records[offset:offset + limit]

    def count(
        self,
        *,
        ragguard_tenant_id: str | None = None,
        application_id: str | None = None,
        status: str | None = None,
        failure_detected: bool | None = None,
    ) -> int:
        with self._lock:
            records = list(self._records.values())
        return len(self._filter(
            records,
            ragguard_tenant_id=ragguard_tenant_id,
            application_id=application_id,
            status=status,
            failure_detected=failure_detected,
        ))

    @staticmethod
    def _validate_page(limit: int, offset: int) -> None:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

    @staticmethod
    def _filter(
        records: list[ObservationRecord],
        *,
        ragguard_tenant_id: str | None,
        application_id: str | None,
        status: str | None,
        failure_detected: bool | None,
    ) -> list[ObservationRecord]:
        filters = (
            ("ragguard_tenant_id", ragguard_tenant_id),
            ("application_id", application_id),
            ("status", status),
        )
        for attribute, value in filters:
            if value is not None:
                records = [
                    record for record in records
                    if getattr(record, attribute) == value
                ]
        if failure_detected is not None:
            records = [
                record for record in records
                if (record.failure is not None) is failure_detected
            ]
        return records
