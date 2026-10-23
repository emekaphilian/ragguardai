import pytest
from fastapi.testclient import TestClient

from ragguard.api.app import app
from ragguard.api.routes import repairs as repair_routes
from ragguard.api.runtime import workspace
from ragguard.observability.application_repository import InMemoryApplicationRepository
from ragguard.tenants.application_registration import ApplicationRegistration

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_query_returns_stable_response_contract(client):
    response = client.post(
        "/api/v1/query",
        json={
            "query": "How do I request a refund?",
            "top_k": 5,
            "method": "hybrid",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert "answer" in body
    assert "rag_status" in body
    assert "retrieval_quality" in body
    assert "sources" in body
    assert "retrieval_method" in body
    assert "latency_ms" in body
    assert "reliability_evaluation" in body
    assert "reliability_failure" in body
    assert body["capability_execution"]["independent_verification"] == {
        "authorization": "not_applicable",
        "performed": False,
        "reason": "managed_index",
    }

    assert isinstance(body["answer"], str)
    assert isinstance(body["retrieval_quality"], dict)
    assert isinstance(body["sources"], list)
    assert isinstance(body["latency_ms"], (int, float))
    evaluation = body["reliability_evaluation"]
    assert evaluation["retrieved_count"] == len(body["sources"])
    assert evaluation["status"] in {"HEALTHY", "DEGRADED", "FAILURE"}
    assert set(evaluation["signals"]) == {
        "no_retrieval",
        "weak_retrieval",
        "duplicate_context",
        "embedding_degraded",
        "retrieval_bypassed",
        "retrieval_not_attempted",
        "retrieval_empty",
        "evidence_insufficient",
        "generation_failed",
        "infrastructure_failed",
        "retrieval_failed",
        "latency_anomaly",
    }


def test_query_lab_can_avoid_recording_controlled_tests(client):
    runs_before = list(workspace.runs)
    failures_before = list(workspace.failures)

    response = client.post(
        "/api/v1/query",
        json={
            "query": "controlled query lab no-match isolation 98f3d2",
            "top_k": 5,
            "method": "hybrid",
            "record_run": False,
        },
    )

    assert response.status_code == 200
    assert workspace.runs == runs_before
    assert workspace.failures == failures_before


def test_repair_route_requires_application_repair_authorization(
    client, monkeypatch,
):
    applications = InMemoryApplicationRepository()
    applications.upsert(ApplicationRegistration(
        ragguard_tenant_id="development",
        application_id="trustassist",
        display_name="TrustAssist",
        environment="development",
        knowledge_source="managed_index",
        vector_namespace="development",
        repair_authorized=False,
    ))
    monkeypatch.setattr(repair_routes, "application_repository", applications)
    invoked = []
    monkeypatch.setattr(
        repair_routes,
        "run_sequential",
        lambda *args, **kwargs: invoked.append(True),
    )

    response = client.post(
        "/api/v1/repair",
        json={
            "query": "How do I request a refund?",
            "answer": "Refunds are available within 30 days of purchase.",
            "relevant_chunk_ids": ["refund:0"],
        },
    )

    assert response.status_code == 403
    assert "has not authorized" in response.json()["detail"]
    assert response.json()["capability_execution"]["repair"] == {
        "authorization": "not_authorized",
        "performed": False,
        "reason": "application_not_authorized",
    }
    assert invoked == []


def test_repair_route_uses_repair_engine_validation(client, monkeypatch):
    applications = InMemoryApplicationRepository()
    applications.upsert(ApplicationRegistration(
        ragguard_tenant_id="development",
        application_id="trustassist",
        display_name="TrustAssist",
        environment="development",
        knowledge_source="managed_index",
        vector_namespace="development",
        repair_authorized=True,
        context_verification_authorized=True,
    ))
    monkeypatch.setattr(repair_routes, "application_repository", applications)
    response = client.post(
        "/api/v1/repair",
        json={
            "query": "How do I request a refund?",
            "answer": "Refunds are available within 30 days of purchase.",
            "relevant_chunk_ids": ["refund:0"],
        },
    )

    assert response.status_code == 200

    body = response.json()
    assert "status" in body
    assert "repair_type" in body
    assert "before_metrics" in body
    assert "after_metrics" in body
    assert "improvement" in body
    assert "validated" in body
    assert "retrieval" in body
    assert body["completed_nodes"][:2] == ["evaluate", "detect"]
    assert "attempted_repairs" in body
    assert "max_repair_attempts" in body
    assert body["capability_execution"]["repair"]["authorization"] == "authorized"
    assert body["capability_execution"]["independent_verification"] == {
        "authorization": "not_applicable",
        "performed": False,
        "reason": "managed_index",
    }


def test_detect_route_uses_failure_detector(client):
    response = client.post(
        "/api/v1/detect",
        json={
            "query": "refund deadline",
            "metrics": {
                "context_precision": 0.1,
                "context_recall": 0.1,
                "faithfulness": 0.9,
                "answer_relevancy": 0.9,
                "citation_accuracy": 0.1,
                "overall_score": 0.42,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["failure_detected"] is True
    assert response.json()["failure_type"] == "LOW_CONTEXT_RECALL"


def test_repair_capabilities_report_only_implemented_strategies(client):
    response = client.get("/api/v1/repair-capabilities")

    assert response.status_code == 200
    capabilities = {item["strategy"]: item for item in response.json()}
    assert capabilities["DEDUPLICATE"]["implemented"] is True
    assert capabilities["HYBRID_RETRIEVAL"]["implemented"] is True
    assert capabilities["RERANK"]["implemented"] is True
    assert capabilities["RECHUNK"]["implemented"] is False
