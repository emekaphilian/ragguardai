from datetime import datetime, timedelta, timezone

import pytest

from ragguard.config import load_settings
from ragguard.observability.recovery_audit import RecoveryAuditRecord
from ragguard.observability.recovery_repository import InMemoryRecoveryAuditRepository
from ragguard.observability.retention import RecoveryRetentionService


def test_retention_deletes_expired_completed_records_but_keeps_running_records():
    repository = InMemoryRecoveryAuditRepository()
    now = datetime.now(timezone.utc)

    expired = RecoveryAuditRecord.create("expired")
    expired.started_at = now - timedelta(days=120)
    expired.complete("escalated")
    expired.completed_at = now - timedelta(days=120)

    active = RecoveryAuditRecord.create("active")
    active.started_at = now - timedelta(days=120)

    recent = RecoveryAuditRecord.create("recent")
    recent.complete("promoted")

    repository.save(expired)
    repository.save(active)
    repository.save(recent)

    service = RecoveryRetentionService(repository, retention_days=90)

    assert service.delete_expired(now - timedelta(days=90)) == 1
    assert repository.get(expired.recovery_id) is None
    assert repository.get(active.recovery_id) is active
    assert repository.get(recent.recovery_id) is recent


def test_retention_rejects_naive_datetime():
    service = RecoveryRetentionService(InMemoryRecoveryAuditRepository())

    with pytest.raises(ValueError, match="timezone-aware"):
        service.delete_expired(datetime(2026, 1, 1))


def test_in_memory_repository_counts_and_pages_filtered_records():
    repository = InMemoryRecoveryAuditRepository()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(5):
        record = RecoveryAuditRecord.create(
            f"graph-{index}",
            tenant_id="customer-a" if index < 4 else "customer-b",
            ragguard_tenant_id="internal-a",
        )
        record.started_at = base + timedelta(seconds=index)
        repository.save(record)

    assert repository.count(
        ragguard_tenant_id="internal-a",
        tenant_id="customer-a",
    ) == 4
    page = repository.list(
        ragguard_tenant_id="internal-a",
        tenant_id="customer-a",
        limit=2,
        offset=1,
    )
    assert [record.graph_run_id for record in page] == ["graph-2", "graph-1"]


def test_audit_retention_settings_load_from_environment(monkeypatch):
    monkeypatch.setenv("RAGGUARD_AUDIT_RETENTION_DAYS", "120")
    monkeypatch.setenv("RAGGUARD_AUDIT_MAX_PAGE_SIZE", "75")
    monkeypatch.setenv("RAGGUARD_EVENT_RETENTION_DAYS", "45")

    settings = load_settings("configs/development.yaml")

    assert settings.audit_retention_days == 120
    assert settings.audit_max_page_size == 75
    assert settings.event_retention_days == 45


def test_audit_retention_settings_must_be_positive(monkeypatch):
    monkeypatch.setenv("RAGGUARD_AUDIT_MAX_PAGE_SIZE", "0")

    with pytest.raises(ValueError, match="audit_max_page_size"):
        load_settings("configs/development.yaml")
