import importlib
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from ragguard.api.runtime import workspace
from ragguard.auth.tenant_context import TenantContext
from ragguard.observability.observation_activity import ObservationRecord
from ragguard.observability.observation_repository import InMemoryObservationRepository

app_module = importlib.import_module("ragguard.api.app")
dashboard_route = importlib.import_module("ragguard.api.routes.dashboard")
repairs_route = importlib.import_module("ragguard.api.routes.repairs")
client = TestClient(app_module.app)


def make_record(
    *,
    observation_id,
    tenant_id,
    application_id,
    failure=None,
    recovery=None,
):
    return ObservationRecord(
        observation_id=observation_id,
        ragguard_tenant_id=tenant_id,
        application_id=application_id,
        created_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        status=(recovery or {}).get("status", "failure" if failure else "healthy"),
        query=f"query for {observation_id}",
        evaluation={
            "status": "FAILURE" if failure else "HEALTHY",
            "retrieved_count": 0 if failure else 2,
            "top_score": 0.9 if not failure else None,
            "score_margin": None,
        },
        observation={
            "source": {"application_id": application_id, "environment": "production"},
            "retrieval_method": "hybrid",
            "retrieval_latency_ms": 40,
            "embedding_degraded": False,
        },
        failure=failure,
        recovery=recovery,
    )


def test_dashboard_runs_and_failures_include_tenant_scoped_observations(monkeypatch):
    tenant_context = TenantContext(
        tenant_id="tenant-a",
        application_id="app-a",
        environment="production",
        user_id=None,
        roles=(),
        vector_namespace="tenant-a",
        policy_version="v1",
        index_version="v1",
    )
    repository = InMemoryObservationRepository()
    repository.save(make_record(
        observation_id="visible-observation",
        tenant_id="tenant-a",
        application_id="app-a",
        failure={
            "failure_id": "failure-a",
            "failure_type": "NO_RETRIEVAL",
            "severity": "high",
            "evidence": ["No chunks retrieved."],
        },
        recovery={"status": "promoted"},
    ))
    repository.save(make_record(
        observation_id="hidden-observation",
        tenant_id="tenant-b",
        application_id="app-b",
        failure={"failure_type": "WEAK_RETRIEVAL", "severity": "medium"},
    ))
    monkeypatch.setattr(dashboard_route, "observation_repository", repository)
    monkeypatch.setattr(repairs_route, "observation_repository", repository)
    monkeypatch.setattr(
        app_module,
        "resolve_request_context",
        lambda request: tenant_context,
    )
    monkeypatch.setattr(workspace, "runs", [{
        "id": "local-run",
        "query": "local workspace query",
        "status": "grounded",
        "method": "hybrid",
        "latency_ms": 8,
        "created_at": "2026-09-29T12:00:00+00:00",
        "quality": {},
        "tenant_id": "tenant-a",
    }])
    monkeypatch.setattr(workspace, "failures", [])

    runs_response = client.get("/api/v1/runs")
    dashboard_response = client.get("/api/v1/dashboard")
    failures_response = client.get("/api/v1/failures")

    assert runs_response.status_code == 200
    runs = runs_response.json()
    assert {run["id"] for run in runs} == {"visible-observation", "local-run"}
    observed_run = next(run for run in runs if run["id"] == "visible-observation")
    assert observed_run["application_id"] == "app-a"
    assert observed_run["retrieved_count"] == 0
    assert observed_run["failure_type"] == "NO_RETRIEVAL"

    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["metrics"]["total_runs"] == 2
    assert dashboard["metrics"]["observation_runs"] == 1
    assert dashboard["metrics"]["total_failures"] == 1
    assert [item["id"] for item in dashboard["recent_failures"]] == ["failure-a"]
    assert {item["id"] for item in dashboard["recent_runs"]} == {
        "visible-observation", "local-run",
    }

    assert failures_response.status_code == 200
    failures = failures_response.json()
    assert len(failures) == 1
    assert failures[0]["type"] == "NO_RETRIEVAL"
    assert failures[0]["status"] == "resolved"