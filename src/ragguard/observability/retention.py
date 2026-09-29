from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ragguard.observability.recovery_repository import RecoveryAuditRepository


class RecoveryRetentionService:
    """Explicit retention operations for completed recovery audit records."""

    def __init__(
        self,
        repository: RecoveryAuditRepository,
        retention_days: int | None = None,
    ) -> None:
        if retention_days is None:
            from ragguard.config import load_settings

            retention_days = load_settings().audit_retention_days
        if retention_days < 1:
            raise ValueError("retention_days must be greater than zero")
        self.repository = repository
        self.retention_days = retention_days

    def delete_expired(self, before: datetime) -> int:
        if before.tzinfo is None:
            raise ValueError("before must be timezone-aware")
        return self.repository.delete_expired(before)

    def delete_by_retention_policy(
        self,
        *,
        now: datetime | None = None,
    ) -> int:
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        before = current_time - timedelta(days=self.retention_days)
        return self.delete_expired(before)
