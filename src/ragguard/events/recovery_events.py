from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ragguard.observability.recovery_audit import RecoveryAuditEvent, RecoveryEventType


@dataclass(frozen=True)
class RecoveryEvent:
    event_id: str
    recovery_id: str
    event_type: RecoveryEventType
    timestamp: datetime
    application_id: str | None = None
    environment: str | None = None
    tenant_id: str | None = None
    ragguard_tenant_id: str | None = None
    attempt: int | None = None
    strategy: str | None = None
    status: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        recovery_id: str,
        event_type: RecoveryEventType,
        **kwargs: Any,
    ) -> "RecoveryEvent":
        return cls(
            event_id=str(uuid4()),
            recovery_id=recovery_id,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            **kwargs,
        )

    @classmethod
    def from_audit_event(cls, event: RecoveryAuditEvent) -> "RecoveryEvent":
        event_type = (
            RecoveryEventType.RECOVERY_STARTED
            if event.event_type == RecoveryEventType.RUN_STARTED
            else event.event_type
        )
        return cls(
            event_id=event.event_id,
            recovery_id=event.recovery_id,
            event_type=event_type,
            timestamp=event.timestamp,
            application_id=event.application_id,
            environment=event.environment,
            tenant_id=event.tenant_id,
            ragguard_tenant_id=event.ragguard_tenant_id,
            attempt=event.attempt,
            strategy=event.strategy,
            status=event.status,
            payload={
                "failure_id": event.failure_id,
                "graph_run_id": event.graph_run_id,
                "before_score": event.before_score,
                "after_score": event.after_score,
                "improvement": event.improvement,
                "validation_valid": event.validation_valid,
                "validation_improved": event.validation_improved,
                "reason": event.reason,
                **event.metadata,
            },
        )
