from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ragguard.observability.recovery_audit import (
    RecoveryAuditRecord,
    record_from_dict,
    record_to_dict,
)


@dataclass(frozen=True)
class RecoveryAuditRow:
    """Database projection used for indexed filters and JSONB serialization."""

    recovery_id: str
    ragguard_tenant_id: str | None
    tenant_id: str | None
    application_id: str | None
    started_at: datetime
    final_status: str
    document: dict[str, Any]

    @classmethod
    def from_record(cls, record: RecoveryAuditRecord) -> "RecoveryAuditRow":
        return cls(
            recovery_id=record.recovery_id,
            ragguard_tenant_id=record.ragguard_tenant_id,
            tenant_id=record.tenant_id,
            application_id=record.application_id,
            started_at=record.started_at,
            final_status=record.final_status,
            document=record_to_dict(record, include_observation=True),
        )

    def to_record(self) -> RecoveryAuditRecord:
        return record_from_dict(self.document)
