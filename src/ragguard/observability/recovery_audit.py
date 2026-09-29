from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class RecoveryEventType(str, Enum):
    RECOVERY_STARTED = "recovery_started"
    RUN_STARTED = "run_started"
    FAILURE_DETECTED = "failure_detected"
    DIAGNOSIS_COMPLETED = "diagnosis_completed"
    REPAIR_PLANNED = "repair_planned"
    REPAIR_STARTED = "repair_started"
    REPAIR_COMPLETED = "repair_completed"
    VALIDATION_COMPLETED = "validation_completed"
    ROLLBACK = "rollback"
    PROMOTED = "promoted"
    ESCALATED = "escalated"
    RUN_COMPLETED = "run_completed"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RecoveryAuditEvent:
    event_id: str
    recovery_id: str
    event_type: RecoveryEventType
    timestamp: datetime

    failure_id: str | None = None
    graph_run_id: str | None = None

    application_id: str | None = None
    environment: str | None = None
    tenant_id: str | None = None
    ragguard_tenant_id: str | None = None

    attempt: int | None = None
    strategy: str | None = None
    status: str | None = None

    before_score: float | None = None
    after_score: float | None = None
    improvement: float | None = None

    validation_valid: bool | None = None
    validation_improved: bool | None = None

    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        recovery_id: str,
        event_type: RecoveryEventType,
        **kwargs: Any,
    ) -> "RecoveryAuditEvent":
        return cls(
            event_id=str(uuid4()),
            recovery_id=recovery_id,
            event_type=event_type,
            timestamp=utc_now(),
            **kwargs,
        )


@dataclass
class RecoveryAuditRecord:
    recovery_id: str
    graph_run_id: str

    started_at: datetime
    completed_at: datetime | None = None

    failure_id: str | None = None
    failure_type: str | None = None

    application_id: str | None = None
    environment: str | None = None
    tenant_id: str | None = None
    ragguard_tenant_id: str | None = None

    final_status: str = "running"

    original_score: float | None = None
    final_score: float | None = None
    improvement: float | None = None
    observation_snapshot: dict[str, Any] | None = None

    attempts: list[dict[str, Any]] = field(default_factory=list)
    events: list[RecoveryAuditEvent] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        graph_run_id: str,
        *,
        failure_id: str | None = None,
        failure_type: str | None = None,
        application_id: str | None = None,
        environment: str | None = None,
        tenant_id: str | None = None,
        ragguard_tenant_id: str | None = None,
        original_score: float | None = None,
        observation_snapshot: dict[str, Any] | None = None,
    ) -> "RecoveryAuditRecord":
        return cls(
            recovery_id=str(uuid4()),
            graph_run_id=graph_run_id,
            started_at=utc_now(),
            failure_id=failure_id,
            failure_type=failure_type,
            application_id=application_id,
            environment=environment,
            tenant_id=tenant_id,
            ragguard_tenant_id=ragguard_tenant_id,
            original_score=original_score,
            observation_snapshot=observation_snapshot,
        )

    def add_event(
        self,
        event_type: RecoveryEventType,
        **kwargs: Any,
    ) -> RecoveryAuditEvent:
        event = RecoveryAuditEvent.create(
            recovery_id=self.recovery_id,
            event_type=event_type,
            failure_id=self.failure_id,
            graph_run_id=self.graph_run_id,
            application_id=self.application_id,
            environment=self.environment,
            tenant_id=self.tenant_id,
            ragguard_tenant_id=self.ragguard_tenant_id,
            **kwargs,
        )
        self.events.append(event)
        return event

    def complete(
        self,
        status: str,
        *,
        final_score: float | None = None,
        improvement: float | None = None,
    ) -> None:
        if self.completed_at is not None:
            return

        self.final_status = status
        self.final_score = final_score
        self.improvement = improvement
        self.completed_at = utc_now()

        terminal_event = {
            "promoted": RecoveryEventType.PROMOTED,
            "escalated": RecoveryEventType.ESCALATED,
        }.get(status)
        if terminal_event is not None:
            self.add_event(
                terminal_event,
                status=status,
                after_score=final_score,
                improvement=improvement,
            )

        self.add_event(
            RecoveryEventType.RUN_COMPLETED,
            status=status,
            after_score=final_score,
            improvement=improvement,
        )


def event_to_dict(event: RecoveryAuditEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "recovery_id": event.recovery_id,
        "event_type": event.event_type.value,
        "timestamp": event.timestamp.isoformat(),
        "failure_id": event.failure_id,
        "graph_run_id": event.graph_run_id,
        "application_id": event.application_id,
        "environment": event.environment,
        "tenant_id": event.tenant_id,
        "ragguard_tenant_id": event.ragguard_tenant_id,
        "attempt": event.attempt,
        "strategy": event.strategy,
        "status": event.status,
        "before_score": event.before_score,
        "after_score": event.after_score,
        "improvement": event.improvement,
        "validation_valid": event.validation_valid,
        "validation_improved": event.validation_improved,
        "reason": event.reason,
        "metadata": event.metadata,
    }


def record_to_dict(
    record: RecoveryAuditRecord,
    *,
    include_observation: bool = False,
) -> dict[str, Any]:
    value = {
        "recovery_id": record.recovery_id,
        "graph_run_id": record.graph_run_id,
        "started_at": record.started_at.isoformat(),
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "failure_id": record.failure_id,
        "failure_type": record.failure_type,
        "application_id": record.application_id,
        "environment": record.environment,
        "tenant_id": record.tenant_id,
        "ragguard_tenant_id": record.ragguard_tenant_id,
        "final_status": record.final_status,
        "original_score": record.original_score,
        "final_score": record.final_score,
        "improvement": record.improvement,
        "attempts": record.attempts,
        "events": [event_to_dict(event) for event in record.events],
    }
    if include_observation:
        value["observation_snapshot"] = record.observation_snapshot
    return value


def record_from_dict(value: dict[str, Any]) -> RecoveryAuditRecord:
    """Reconstruct a typed audit record from a JSON-compatible document."""
    events = []
    for event_data in value.get("events", []):
        event_fields = dict(event_data)
        event_fields["event_type"] = RecoveryEventType(event_fields["event_type"])
        event_fields["timestamp"] = datetime.fromisoformat(event_fields["timestamp"])
        events.append(RecoveryAuditEvent(**event_fields))

    started_at = value["started_at"]
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at)
    completed_at = value.get("completed_at")
    if isinstance(completed_at, str):
        completed_at = datetime.fromisoformat(completed_at)

    return RecoveryAuditRecord(
        recovery_id=value["recovery_id"],
        graph_run_id=value["graph_run_id"],
        started_at=started_at,
        completed_at=completed_at,
        failure_id=value.get("failure_id"),
        failure_type=value.get("failure_type"),
        application_id=value.get("application_id"),
        environment=value.get("environment"),
        tenant_id=value.get("tenant_id"),
        ragguard_tenant_id=value.get("ragguard_tenant_id"),
        final_status=value.get("final_status", "running"),
        original_score=value.get("original_score"),
        final_score=value.get("final_score"),
        improvement=value.get("improvement"),
        observation_snapshot=value.get("observation_snapshot"),
        attempts=list(value.get("attempts", [])),
        events=events,
    )
