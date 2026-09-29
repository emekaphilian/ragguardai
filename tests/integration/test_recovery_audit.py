from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from ragguard.api.app import app
from ragguard.api.recovery_service import ObservationRecoveryService
from ragguard.api.routes import observations as observations_route
from ragguard.config import ServiceAuthSettings, Settings
from ragguard.detection.live_detector import LiveFailureDetector
from ragguard.observability.recovery_audit import (
    RecoveryAuditRecord,
    RecoveryEventType,
)
from ragguard.observability.recovery_repository import (
    InMemoryRecoveryAuditRepository,
)
from ragguard.tenants.models import TenantPolicy


def test_recovery_audit_record_tracks_lifecycle():
    record = RecoveryAuditRecord.create(
        graph_run_id="graph-123",
        failure_id="failure-123",
        failure_type="LOW_CONTEXT_PRECISION",
        application_id="trustassist",
        environment="development",
        tenant_id="customer-123",
        ragguard_tenant_id="development",
        original_score=0.65,
    )

    record.add_event(RecoveryEventType.FAILURE_DETECTED, status="failed")
    record.add_event(
        RecoveryEventType.REPAIR_PLANNED,
        attempt=1,
        strategy="RERANK",
    )
    record.add_event(
        RecoveryEventType.VALIDATION_COMPLETED,
        attempt=1,
        strategy="RERANK",
        before_score=0.65,
        after_score=1.0,
        improvement=0.35,
        validation_valid=True,
        validation_improved=True,
    )
    record.complete("promoted", final_score=1.0, improvement=0.35)

    assert record.final_status == "promoted"
    assert record.failure_id == "failure-123"
    assert record.graph_run_id == "graph-123"
    assert record.application_id == "trustassist"
    assert record.tenant_id == "customer-123"
    assert record.ragguard_tenant_id == "development"

    event_types = [event.event_type for event in record.events]
    assert RecoveryEventType.FAILURE_DETECTED in event_types
    assert RecoveryEventType.REPAIR_PLANNED in event_types
    assert RecoveryEventType.VALIDATION_COMPLETED in event_types
    assert RecoveryEventType.PROMOTED in event_types
    assert event_types.count(RecoveryEventType.RUN_COMPLETED) == 1


def test_repository_filters_external_and_internal_tenants():
    repository = InMemoryRecoveryAuditRepository()
    first = RecoveryAuditRecord.create(
        graph_run_id="graph-1",
        application_id="trustassist",
        tenant_id="customer-a",
        ragguard_tenant_id="internal-a",
    )
    second = RecoveryAuditRecord.create(
        graph_run_id="graph-2",
        application_id="trustassist",
        tenant_id="customer-b",
        ragguard_tenant_id="internal-b",
    )
    repository.save(first)
    repository.save(second)

    assert repository.list(ragguard_tenant_id="internal-a") == [first]
    assert repository.list(tenant_id="customer-b") == [second]
    assert repository.list(application_id="other-app") == []


def test_external_observation_tenant_is_audit_metadata_only():
    record = RecoveryAuditRecord.create(
        graph_run_id="graph-123",
        application_id="trustassist",
        tenant_id="customer-123",
        ragguard_tenant_id="development",
    )

    assert record.tenant_id == "customer-123"
    assert record.ragguard_tenant_id == "development"


def test_observation_recovery_is_persisted_and_retrievable(monkeypatch):
    settings = Settings(
        tenant_policies=(
            TenantPolicy(
                tenant_id="development",
                application_id="trustassist",
                environment="development",
                vector_namespace="development",
            ),
        ),
        service_auth=ServiceAuthSettings(
            token="audit-test-token",
            application="trustassist",
            tenant_id="development",
        ),
    )
    monkeypatch.setattr(observations_route, "load_settings", lambda: settings)
    monkeypatch.setattr(
        observations_route,
        "recovery_service",
        ObservationRecoveryService(
            detector=LiveFailureDetector(),
            recovery_repository=observations_route.recovery_repository,
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/observations",
        headers={"Authorization": "Bearer audit-test-token"},
        json={
            "contract_version": "v1",
            "source": {
                "application_id": "trustassist",
                "environment": "test",
            },
            "query": "refund policy",
            "retrieved_chunks": [],
            "retrieval_method": "vector",
        },
    )

    assert response.status_code == 200
    recovery_id = response.json()["recovery"]["recovery_id"]
    record = observations_route.recovery_repository.get(recovery_id)
    assert record is not None
    assert record.final_status == "escalated"
    assert record.tenant_id is None
    assert record.ragguard_tenant_id == "development"
    assert record.observation_snapshot["query"] == "refund policy"
    assert record.improvement is None
    repair_plan = next(
        event for event in record.events
        if event.event_type == RecoveryEventType.REPAIR_PLANNED
    )
    assert repair_plan.attempt is None

    detail = client.get(f"/api/v1/recoveries/{recovery_id}")
    assert detail.status_code == 200
    assert detail.json()["recovery_id"] == recovery_id
    assert "observation_snapshot" not in detail.json()
    assert detail.json()["events"][-1]["event_type"] == "run_completed"


def test_recovery_routes_hide_records_from_other_internal_tenants(monkeypatch):
    settings = Settings(
        tenant_policies=(
            TenantPolicy(
                tenant_id="development",
                application_id="trustassist",
                environment="development",
                vector_namespace="development",
            ),
            TenantPolicy(
                tenant_id="internal-other",
                application_id="trustassist",
                environment="development",
                vector_namespace="other",
            ),
        ),
    )
    monkeypatch.setattr(
        "ragguard.api.middleware.load_settings",
        lambda: settings,
    )
    record = RecoveryAuditRecord.create(
        graph_run_id="graph-isolation",
        application_id="trustassist",
        tenant_id="external-customer",
        ragguard_tenant_id="development",
    )
    observations_route.recovery_repository.save(record)
    client = TestClient(app)

    listed = client.get(
        "/api/v1/recoveries",
        headers={"X-RAGGuard-Tenant": "internal-other"},
    )
    detail = client.get(
        f"/api/v1/recoveries/{record.recovery_id}",
        headers={"X-RAGGuard-Tenant": "internal-other"},
    )

    assert listed.status_code == 200
    page = listed.json()
    assert page["items"] == []
    assert page["total"] == 0
    assert page["page"] == 1
    assert page["has_next"] is False
    assert detail.status_code == 404


def test_recovery_list_pages_scoped_records_and_enforces_configured_max(monkeypatch):
    page_settings = Settings(
        tenant_policies=(
            TenantPolicy(
                tenant_id="development",
                application_id="trustassist",
                environment="development",
                vector_namespace="development",
            ),
        ),
        audit_max_page_size=2,
    )
    monkeypatch.setattr(
        "ragguard.api.middleware.load_settings",
        lambda: page_settings,
    )
    monkeypatch.setattr(
        "ragguard.api.recovery_routes.load_settings",
        lambda: page_settings,
    )
    source_tenant = "pagination-customer"
    base = datetime.now(timezone.utc) - timedelta(minutes=5)
    for index in range(5):
        record = RecoveryAuditRecord.create(
            graph_run_id=f"pagination-{index}",
            application_id="trustassist",
            tenant_id=source_tenant,
            ragguard_tenant_id="development",
        )
        record.started_at = base + timedelta(seconds=index)
        observations_route.recovery_repository.save(record)

    client = TestClient(app)
    page_two = client.get(
        "/api/v1/recoveries",
        params={"tenant_id": source_tenant, "page": 2, "page_size": 2},
    )
    page_three = client.get(
        "/api/v1/recoveries",
        params={"tenant_id": source_tenant, "page": 3, "page_size": 2},
    )
    oversized = client.get(
        "/api/v1/recoveries",
        params={"tenant_id": source_tenant, "page_size": 3},
    )

    assert page_two.status_code == 200
    assert len(page_two.json()["items"]) == 2
    assert page_two.json()["page"] == 2
    assert page_two.json()["page_size"] == 2
    assert page_two.json()["total"] == 5
    assert page_two.json()["has_next"] is True
    assert page_three.status_code == 200
    assert len(page_three.json()["items"]) == 1
    assert page_three.json()["has_next"] is False
    assert oversized.status_code == 422
