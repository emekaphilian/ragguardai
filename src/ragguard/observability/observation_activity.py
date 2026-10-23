from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    """Durable result of evaluating one externally reported RAG observation."""

    observation_id: str
    ragguard_tenant_id: str
    application_id: str
    created_at: datetime
    status: str
    query: str
    evaluation: dict[str, Any]
    observation: dict[str, Any]
    failure: dict[str, Any] | None
    recovery: dict[str, Any] | None
    capability_execution: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        ragguard_tenant_id: str,
        application_id: str,
        status: str,
        query: str,
        evaluation: dict[str, Any],
        observation: dict[str, Any],
        failure: dict[str, Any] | None,
        recovery: dict[str, Any] | None,
        capability_execution: dict[str, dict[str, Any]] | None = None,
    ) -> ObservationRecord:
        return cls(
            observation_id=str(uuid4()),
            ragguard_tenant_id=ragguard_tenant_id,
            application_id=application_id,
            created_at=datetime.now(timezone.utc),
            status=status,
            query=query,
            evaluation=evaluation,
            observation=observation,
            failure=failure,
            recovery=recovery,
            capability_execution=capability_execution or {},
        )
