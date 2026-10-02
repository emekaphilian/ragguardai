import pytest
from fastapi.testclient import TestClient

from ragguard.api.app import app
from ragguard.api.recovery_service import ObservationRecoveryService
from ragguard.api.routes import observations as observations_route
from ragguard.common.enums import RepairType
from ragguard.common.schemas import Chunk, RepairResult, ValidationResult
from ragguard.config import ServiceAuthSettings, Settings
from ragguard.detection.live_detector import LiveFailureDetector
from ragguard.diagnosis.diagnostic_agent import diagnose
from ragguard.evaluation.evaluator import Evaluator
from ragguard.events.bus import InMemoryRecoveryEventBus
from ragguard.repair.repair_engine import RepairEngine
from ragguard.storage.vector_store import VectorStore
from ragguard.observability.application_repository import InMemoryApplicationRepository
from ragguard.tenants.application_registration import ApplicationRegistration
from ragguard.tenants.models import TenantPolicy
from ragguard.observability.recovery_audit import RecoveryEventType


@pytest.fixture
def observation_client(monkeypatch):
    applications = InMemoryApplicationRepository()
    applications.upsert(ApplicationRegistration(
        ragguard_tenant_id="development",
        application_id="trustassist",
        display_name="TrustAssist",
        environment="test",
        knowledge_source="managed_index",
        vector_namespace="development",
        repair_authorized=True,
    ))
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
            token="test-token",
            application="trustassist",
            tenant_id="development",
        ),
    )
    monkeypatch.setattr(observations_route, "load_settings", lambda: settings)
    monkeypatch.setattr(observations_route, "application_repository", applications)
    monkeypatch.setattr(
        observations_route,
        "recovery_service",
        ObservationRecoveryService(
            detector=LiveFailureDetector(),
            diagnosis_fn=diagnose,
            recovery_repository=observations_route.recovery_repository,
        ),
    )
    return TestClient(app)


def observation_payload(*, chunks=None, application_id="trustassist"):
    if chunks is None:
        chunks = [
            {"id": "chunk-1", "score": 0.9},
            {"id": "chunk-2", "score": 0.8},
        ]
    return {
        "contract_version": "v1",
        "source": {
            "application_id": application_id,
            "environment": "test",
        },
        "query": "refund request deadline",
        "retrieved_chunks": chunks,
        "retrieval_method": "hybrid",
        "embedding_degraded": False,
        "retrieval_latency_ms": 20.0,
        "answer": "Refunds are available within 30 days.",
    }


def test_healthy_observation_returns_existing_contract_without_recovery(
    observation_client,
    monkeypatch,
):
    def unexpected_recovery(**kwargs):
        raise AssertionError("Healthy observations must not enter recovery.")

    monkeypatch.setattr(
        observations_route.recovery_service,
        "recover",
        unexpected_recovery,
    )
    response = observation_client.post(
        "/api/v1/observations",
        json=observation_payload(),
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["evaluation"]["status"] == "HEALTHY"
    assert body["failure"] is None
    assert body["recovery"] is None


def test_external_failure_without_repair_capability_escalates_safely(
    observation_client,
):
    response = observation_client.post(
        "/api/v1/observations",
        json=observation_payload(chunks=[]),
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "escalated"
    assert body["failure"]["failure_type"] == "NO_RETRIEVAL"
    assert body["recovery"]["failure_detected"] is True
    assert body["recovery"]["status"] == "escalated"
    assert body["recovery"]["attempts"] == []
    assert "diagnose" in body["recovery"]["completed_nodes"]
    assert "retrieval_result" not in body["recovery"]
    audit = observations_route.recovery_repository.get(
        body["recovery"]["recovery_id"]
    )
    assert audit is not None
    assert audit.attempts == []
    plan_event = next(
        event for event in audit.events
        if event.event_type == RecoveryEventType.REPAIR_PLANNED
    )
    assert plan_event.status == "unavailable"
    assert plan_event.reason


def local_recovery_service(
    *,
    repair_engine=None,
    diagnosis_fn=diagnose,
    event_bus=None,
):
    store = VectorStore()
    store.add(
        [
            Chunk(
                chunk_id="duplicate-1",
                document_id="noise-1",
                text="Refund request general information.",
            ),
            Chunk(
                chunk_id="duplicate-2",
                document_id="noise-2",
                text="Refund request general information.",
            ),
            Chunk(
                chunk_id="relevant",
                document_id="policy",
                text="Refunds are available within 30 days.",
            ),
        ],
        namespace="development",
    )
    contexts = []

    def retrieval_builder(observation, context):
        contexts.append((context.tenant_id, observation.source.application_id))
        return store.search(
            observation.query,
            top_k=len(store.chunks),
            namespace=context.vector_namespace,
        )

    return (
        ObservationRecoveryService(
            detector=LiveFailureDetector(),
            diagnosis_fn=diagnosis_fn,
            repair_engine=repair_engine or RepairEngine(),
            store=store,
            evaluator=Evaluator(),
            relevant_ids={"relevant"},
            retrieval_builder=retrieval_builder,
            recovery_repository=observations_route.recovery_repository,
            event_bus=event_bus,
        ),
        contexts,
    )


def duplicate_observation_payload():
    return observation_payload(
        chunks=[
            {"id": "same-1", "score": 0.9},
            {"id": "same-1", "score": 0.85},
            {"id": "same-2", "score": 0.8},
            {"id": "same-2", "score": 0.75},
        ]
    )


def test_observation_failure_is_repaired_and_promoted(
    observation_client,
    monkeypatch,
):
    service, contexts = local_recovery_service()
    monkeypatch.setattr(observations_route, "recovery_service", service)

    response = observation_client.post(
        "/api/v1/observations",
        json=duplicate_observation_payload(),
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recovery"]["failure_detected"] is True
    assert body["recovery"]["status"] == "promoted"
    assert body["recovery"]["repair_capability"] == "available"
    assert body["recovery"]["repair_authorization"] == "authorized"
    assert body["recovery"]["repair_attempted"] is True
    assert body["status"] == "promoted"
    assert body["recovery"]["attempts"][-1]["strategy"] == "DEDUPLICATE"
    assert body["recovery"]["attempts"][-1]["status"] == "promoted"
    assert body["recovery"]["final_score"] > body["recovery"]["original_score"]
    assert contexts == [("development", "trustassist")]
    assert "retrieval_result" not in body["recovery"]
    audit = observations_route.recovery_repository.get(
        body["recovery"]["recovery_id"]
    )
    assert audit is not None
    assert audit.final_status == "promoted"
    assert audit.repair_capability == "available"
    assert audit.repair_authorization == "authorized"
    assert audit.repair_attempted is True
    assert audit.tenant_id is None
    assert audit.ragguard_tenant_id == "development"
    assert [event.event_type.value for event in audit.events][-2:] == [
        "promoted",
        "run_completed",
    ]


class AlwaysFailRepairEngine:
    def execute(
        self,
        repair_type,
        store,
        query,
        before_metrics,
        relevant_ids,
        evaluator,
        answer,
        **kwargs,
    ):
        before_retrieval = kwargs["before_retrieval"]
        return RepairResult(
            repair_id=f"failed-{repair_type.value}",
            failure_id="",
            repair_type=repair_type,
            before_metrics=before_metrics,
            after_metrics=before_metrics,
            improvement=-1.0,
            status="rejected",
            before_retrieval=before_retrieval,
            after_retrieval=before_retrieval.model_copy(
                update={"documents": [], "scores": []}
            ),
        )

    def validate(self, result):
        return ValidationResult(
            valid=True,
            improved=False,
            score_delta=result.improvement,
            message="Repair failed validation.",
        )


def test_observation_failure_exhausts_repair_budget(
    observation_client,
    monkeypatch,
):
    def recommend_three_repairs(failure):
        diagnosis = diagnose(failure)
        diagnosis.recommended_repairs = [
            RepairType.DEDUPLICATE,
            RepairType.RERANK,
            RepairType.HYBRID_RETRIEVAL,
        ]
        return diagnosis

    service, contexts = local_recovery_service(
        repair_engine=AlwaysFailRepairEngine(),
        diagnosis_fn=recommend_three_repairs,
    )
    monkeypatch.setattr(observations_route, "recovery_service", service)

    response = observation_client.post(
        "/api/v1/observations",
        json=duplicate_observation_payload(),
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    body = response.json()
    recovery = body["recovery"]
    assert recovery["failure_detected"] is True
    assert recovery["status"] == "escalated"
    assert [attempt["strategy"] for attempt in recovery["attempts"]] == [
        "DEDUPLICATE",
        "RERANK",
        "HYBRID_RETRIEVAL",
    ]
    assert all(attempt["status"] == "rolled_back" for attempt in recovery["attempts"])
    assert len(recovery["attempts"]) == 3
    assert recovery["completed_nodes"].count("rollback") == 3
    assert recovery["completed_nodes"].count("escalate") == 1
    assert contexts == [("development", "trustassist")]
    audit = observations_route.recovery_repository.get(recovery["recovery_id"])
    assert audit is not None
    assert audit.final_status == "escalated"
    assert [attempt["status"] for attempt in audit.attempts] == [
        "rolled_back",
        "rolled_back",
        "rolled_back",
    ]


def test_observation_recovery_publishes_lifecycle_events(
    observation_client,
    monkeypatch,
):
    event_bus = InMemoryRecoveryEventBus()
    service, _ = local_recovery_service(event_bus=event_bus)
    monkeypatch.setattr(observations_route, "recovery_service", service)

    response = observation_client.post(
        "/api/v1/observations",
        json=duplicate_observation_payload(),
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    recovery_id = response.json()["recovery"]["recovery_id"]
    events = [event for event in event_bus.recent() if event.recovery_id == recovery_id]
    event_types = [event.event_type for event in events]
    assert event_types[0] == RecoveryEventType.RECOVERY_STARTED
    assert RecoveryEventType.FAILURE_DETECTED in event_types
    assert RecoveryEventType.REPAIR_STARTED in event_types
    assert RecoveryEventType.VALIDATION_COMPLETED in event_types
    assert RecoveryEventType.PROMOTED in event_types
    assert event_types[-1] == RecoveryEventType.RUN_COMPLETED
    assert all(event.tenant_id is None for event in events)
    assert all(event.ragguard_tenant_id == "development" for event in events)
    audit = observations_route.recovery_repository.get(recovery_id)
    assert audit is not None
    validation = next(
        event for event in audit.events
        if event.event_type == RecoveryEventType.VALIDATION_COMPLETED
    )
    assert validation.metadata["before_retrieval"]["retrieved_chunks"] >= 0
    assert validation.metadata["after_retrieval"]["retrieved_chunks"] >= 0
