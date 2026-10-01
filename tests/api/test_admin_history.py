import importlib

from fastapi.testclient import TestClient

from ragguard.api.app import app
from ragguard.observability.observation_activity import ObservationRecord
from ragguard.observability.observation_repository import InMemoryObservationRepository
from ragguard.observability.recovery_repository import InMemoryRecoveryAuditRepository
from ragguard.observability.recovery_audit import RecoveryAuditRecord

admin_route = importlib.import_module("ragguard.api.routes.admin")
client = TestClient(app)


def seed_repositories(monkeypatch):
    observations = InMemoryObservationRepository()
    observations.save(ObservationRecord.create(
        ragguard_tenant_id="internal",
        application_id="trustassist",
        status="healthy",
        query="test query",
        evaluation={"status": "HEALTHY"},
        observation={"query": "test query"},
        failure=None,
        recovery=None,
    ))
    recoveries = InMemoryRecoveryAuditRepository()
    recoveries.save(RecoveryAuditRecord.create(
        graph_run_id="graph-1",
        application_id="trustassist",
    ))
    monkeypatch.setattr(admin_route, "observation_repository", observations)
    monkeypatch.setattr(admin_route, "recovery_repository", recoveries)
    return observations, recoveries


def test_history_clear_requires_admin_token_and_explicit_confirmation(monkeypatch):
    observations, recoveries = seed_repositories(monkeypatch)
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-secret")

    unauthorized = client.delete(
        "/api/v1/admin/history",
        headers={"Authorization": "Bearer service-secret", "X-Confirm-Delete": "clear-all-history"},
    )
    assert unauthorized.status_code == 401
    assert observations.count() == 1
    assert recoveries.count() == 1

    unconfirmed = client.delete(
        "/api/v1/admin/history",
        headers={"Authorization": "Bearer admin-secret"},
    )
    assert unconfirmed.status_code == 400
    assert observations.count() == 1
    assert recoveries.count() == 1


def test_history_clear_removes_records_with_admin_confirmation(monkeypatch):
    observations, recoveries = seed_repositories(monkeypatch)
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-secret")

    response = client.delete(
        "/api/v1/admin/history",
        headers={
            "Authorization": "Bearer admin-secret",
            "X-Confirm-Delete": "clear-all-history",
        },
    )

    assert response.status_code == 200
    assert response.json()["deleted_observations"] == 1
    assert response.json()["deleted_recoveries"] == 1
    assert observations.count() == 0
    assert recoveries.count() == 0
