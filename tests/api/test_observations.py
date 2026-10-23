from dataclasses import replace
from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from ragguard.auth.service_auth import authenticate_service
from ragguard.api.app import app
from ragguard.api.routes import observations as observations_route
from ragguard.api.external_repair import ExternalRepairResult
from ragguard.common.enums import RepairType
from ragguard.common.schemas import DiagnosisResult
from ragguard.config import ServiceAuthSettings, Settings, load_settings
from ragguard.evaluation.live import RAGObservation
from ragguard.observability.observation_repository import InMemoryObservationRepository
from ragguard.tenants.models import TenantPolicy
from ragguard.observability.application_repository import InMemoryApplicationRepository
from ragguard.tenants.application_registration import ApplicationRegistration

client = TestClient(app)


@pytest.fixture(autouse=True)
def configure_service_auth(monkeypatch):
    observation_repository = InMemoryObservationRepository()
    application_repository = InMemoryApplicationRepository()
    application_repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="development",
        application_id="trustassist",
        display_name="TrustAssist",
        environment="production",
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
            token="test-service-token",
            application="trustassist",
            tenant_id="development",
        ),
    )
    monkeypatch.setattr(
        "ragguard.api.routes.observations.load_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        observations_route,
        "observation_repository",
        observation_repository,
    )
    monkeypatch.setattr(
        observations_route,
        "application_repository",
        application_repository,
    )
    return observation_repository


def post_observation(
    payload,
    authorization="Bearer test-service-token",
    source_application="trustassist",
    source_tenant_id=None,
    contract_version="v1",
):
    request_body = {
        "contract_version": contract_version,
        "source": {
            "application_id": source_application,
            "environment": "production",
        },
        **payload,
    }
    if source_tenant_id is not None:
        request_body["source"]["source_tenant_id"] = source_tenant_id
    headers = {}
    if authorization is not None:
        headers["Authorization"] = authorization
    return client.post(
        "/api/v1/observations",
        json=request_body,
        headers=headers,
    )


def test_observations_healthy_retrieval(configure_service_auth):
    response = post_observation(
        {
            "query": "What payment methods are supported?",
            "retrieved_chunks": [
                {"id": "c1", "score": 0.86},
                {"id": "c2", "score": 0.79},
                {"id": "c3", "score": 0.54},
            ],
            "retrieval_method": "hybrid",
            "embedding_degraded": False,
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["evaluation"]["status"] == "HEALTHY"
    assert body["evaluation"]["retrieved_count"] == 3
    assert body["evaluation"]["top_score"] == 0.86
    assert body["evaluation"]["duplicate_ratio"] == 0.0
    assert body["failure"] is None
    assert body["capability_execution"]["context_verification"] == {
        "authorization": "not_authorized",
        "performed": False,
        "reason": "application_not_authorized",
    }
    assert body["capability_execution"]["independent_verification"] == {
        "authorization": "not_applicable",
        "performed": False,
        "reason": "managed_index",
    }
    assert body["capability_execution"]["repair"] == {
        "authorization": "authorized",
        "performed": False,
        "reason": "no_failure_detected",
    }
    records = configure_service_auth.list()
    assert len(records) == 1
    assert records[0].status == "healthy"
    assert records[0].ragguard_tenant_id == "development"
    assert records[0].application_id == "trustassist"
    assert records[0].query == "What payment methods are supported?"
    assert records[0].evaluation["status"] == "HEALTHY"
    assert records[0].failure is None
    assert records[0].recovery is None
    assert records[0].capability_execution == body["capability_execution"]


def test_source_tenant_is_recorded_without_changing_ragguard_scope(
    configure_service_auth,
):
    response = post_observation(
        {
            "query": "What payment methods are supported?",
            "retrieved_chunks": [{"id": "c1", "score": 0.86}],
        },
        source_tenant_id="source-customer-17",
    )

    assert response.status_code == 200
    record = configure_service_auth.list()[0]
    assert record.ragguard_tenant_id == "development"
    assert record.observation["source"]["source_tenant_id"] == "source-customer-17"


def test_observation_rejects_unknown_v1_fields():
    response = post_observation(
        {
            "query": "What payment methods are supported?",
            "retrieved_chunks": [],
            "ragguard_tenant_id": "caller-selected-tenant",
        },
    )

    assert response.status_code == 422


def test_observations_no_retrieval(configure_service_auth):
    response = post_observation(
        {
            "query": "What payment methods are supported?",
            "retrieved_chunks": [],
            "retrieval_method": "hybrid",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["evaluation"]["status"] == "FAILURE"
    assert body["evaluation"]["signals"]["no_retrieval"] is True

    assert body["failure"] is not None
    assert body["failure"]["failure_type"] == "NO_RETRIEVAL"
    assert body["failure"]["severity"] == "high"
    assert body["status"] == "repair_not_authorized"
    assert body["recovery"]["repair_authorization"] == "authorized"
    assert body["recovery"]["repair_attempted"] is False
    assert "not authorized context verification" in body["recovery"][
        "authorization_reason"
    ]
    records = configure_service_auth.list()
    assert len(records) == 1
    assert records[0].status == body["status"]
    assert records[0].failure["failure_type"] == "NO_RETRIEVAL"
    assert records[0].recovery["status"] == body["recovery"]["status"]


def test_observations_intentional_retrieval_bypass_is_healthy(
    configure_service_auth,
):
    response = post_observation(
        {
            "query": "Thanks, that answers my question.",
            "retrieved_chunks": [],
            "retrieval_required": False,
            "retrieval_attempted": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["evaluation"]["retrieval_outcome"] == "not_required"
    assert body["evaluation"]["signals"]["retrieval_bypassed"] is True
    assert body["evaluation"]["signals"]["no_retrieval"] is False
    assert body["failure"] is None
    assert body["recovery"] is None
    assert configure_service_auth.list()[0].status == "healthy"


def test_observations_reject_unsupported_contract_version():
    response = post_observation(
        {
            "query": "What payment methods are supported?",
            "retrieved_chunks": [],
        },
        contract_version="v2",
    )

    assert response.status_code == 422


def test_failed_observation_is_saved_if_recovery_raises(
    configure_service_auth,
    monkeypatch,
):
    application = observations_route.application_repository.get(
        "development",
        "trustassist",
        "production",
    )
    observations_route.application_repository.upsert(
        replace(application, context_verification_authorized=True)
    )

    def fail_recovery(**kwargs):
        raise RuntimeError("recovery unavailable")

    monkeypatch.setattr(
        observations_route.recovery_service,
        "recover",
        fail_recovery,
    )
    observation = RAGObservation.model_validate(
        {
            "contract_version": "v1",
            "source": {
                "application_id": "trustassist",
                "environment": "production",
            },
            "query": "What payment methods are supported?",
            "retrieved_chunks": [],
        }
    )

    with pytest.raises(RuntimeError, match="recovery unavailable"):
        observations_route.observe(
            observation,
            authorization="Bearer test-service-token",
        )

    records = configure_service_auth.list()
    assert len(records) == 1
    assert records[0].status == "failure"
    assert records[0].failure["failure_type"] == "NO_RETRIEVAL"
    assert records[0].recovery is None


def test_observations_weak_retrieval():
    response = post_observation(
        {
            "query": "What payment methods are supported?",
            "retrieved_chunks": [
                {"id": "c1", "score": 0.29},
                {"id": "c2", "score": 0.22},
            ],
            "retrieval_method": "hybrid",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["evaluation"]["status"] == "DEGRADED"
    assert body["evaluation"]["signals"]["weak_retrieval"] is True

    assert body["failure"] is not None
    assert body["failure"]["failure_type"] == "WEAK_RETRIEVAL"
    assert body["failure"]["metadata"]["source"] == {
        "application_id": "trustassist",
        "environment": "production",
    }


def test_observations_embedding_degraded():
    response = post_observation(
        {
            "query": "What payment methods are supported?",
            "retrieved_chunks": [
                {"id": "c1", "score": 0.86},
                {"id": "c2", "score": 0.79},
            ],
            "retrieval_method": "keyword_fallback",
            "embedding_degraded": True,
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["evaluation"]["status"] == "DEGRADED"
    assert body["evaluation"]["signals"]["embedding_degraded"] is True

    assert body["failure"] is not None
    assert body["failure"]["failure_type"] == "EMBEDDING_DEGRADED"


def test_observations_duplicate_context():
    response = post_observation(
        {
            "query": "What payment methods are supported?",
            "retrieved_chunks": [
                {"id": "c1", "score": 0.86},
                {"id": "c1", "score": 0.79},
                {"id": "c2", "score": 0.54},
                {"id": "c2", "score": 0.50},
            ],
            "retrieval_method": "hybrid",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["evaluation"]["status"] == "DEGRADED"
    assert body["evaluation"]["signals"]["duplicate_context"] is True
    assert body["evaluation"]["duplicate_ratio"] == 0.5

    assert body["failure"] is not None
    assert body["failure"]["failure_type"] == "DUPLICATE_CONTEXT"


def test_observations_requires_service_authentication():
    response = post_observation(
        {
            "query": "What payment methods are supported?",
            "retrieved_chunks": [],
        },
        authorization=None,
    )

    assert response.status_code == 401


def test_hash_backed_onboarding_credential_delivers_observation_without_repair(
    configure_service_auth,
):
    token = "one-time-onboarding-credential"
    observations_route.application_repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="development",
        application_id="new-rag-app",
        display_name="New RAG App",
        environment="production",
        knowledge_source="observation_only",
        observation_token_hash=sha256(token.encode("utf-8")).hexdigest(),
    ))

    response = client.post(
        "/api/v1/observations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "contract_version": "v1",
            "source": {
                "application_id": "new-rag-app",
                "environment": "production",
            },
            "query": "[RAGGuard connection test]",
            "retrieved_chunks": [{"id": "connection-check", "score": 1.0}],
            "retrieval_method": "connection_test",
            "retrieval_required": False,
            "retrieval_attempted": False,
            "generation_status": "succeeded",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recovery"] is None
    assert body["capability_execution"]["repair"]["authorization"] == "not_authorized"
    assert body["capability_execution"]["repair"]["performed"] is False
    assert configure_service_auth.count() == 1


def test_observation_source_keeps_source_tenant_distinct_from_ragguard_tenant():
    from ragguard.evaluation.live import ObservationSource

    source = ObservationSource(
        application_id="tenant-app",
        environment="production",
        source_tenant_id="source-customer",
    )
    assert source.source_tenant_id == "source-customer"
    assert "ragguard_tenant_id" not in ObservationSource.model_fields


def test_registered_observation_adapter_records_repair_unauthorized(monkeypatch):
    applications = InMemoryApplicationRepository()
    applications.upsert(ApplicationRegistration(
        ragguard_tenant_id="development",
        application_id="legal-rag",
        display_name="Legal RAG",
        environment="production",
        knowledge_source="observation_only",
        observation_token_env_var="RAGGUARD_LEGAL_RAG_TOKEN",
    ))
    monkeypatch.setattr(observations_route, "application_repository", applications)
    monkeypatch.setenv("RAGGUARD_LEGAL_RAG_TOKEN", "legal-rag-token")

    def forbidden_recovery(**kwargs):
        pytest.fail("An unauthorized repair must not enter the recovery workflow.")

    monkeypatch.setattr(
        observations_route.recovery_service,
        "recover",
        forbidden_recovery,
    )
    response = post_observation(
        {
            "query": "What is the retention period?",
            "retrieved_chunks": [],
            "retrieval_method": "vector",
        },
        authorization="Bearer legal-rag-token",
        source_application="legal-rag",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "repair_not_authorized"
    assert body["failure"]["failure_type"] == "NO_RETRIEVAL"
    assert body["recovery"]["status"] == "repair_not_authorized"
    assert body["recovery"]["repair_capability"] == "available"
    assert body["recovery"]["repair_supported"] is False
    assert body["recovery"]["repair_eligible"] is False
    assert body["recovery"]["diagnosis"]["root_cause"] == "NO_RETRIEVAL"
    assert "retrieval_outcome=unknown" in body["recovery"]["diagnosis"]["evidence"]
    assert body["recovery"]["repair_authorization"] == "not_authorized"
    assert body["recovery"]["repair_attempted"] is False
    assert body["capability_execution"]["repair"] == {
        "authorization": "not_authorized",
        "performed": False,
        "reason": "application_not_authorized",
    }
    assert body["recovery"]["authorization_source"] == "application_registration"
    assert "has not authorized" in body["recovery"]["authorization_reason"]
    saved_observation = observations_route.observation_repository.list()[0]
    assert saved_observation.recovery == body["recovery"]
    audit = observations_route.recovery_repository.get(body["recovery"]["recovery_id"])
    assert audit is not None
    assert audit.graph_run_id is None
    assert audit.final_status == "repair_not_authorized"
    assert audit.repair_attempted is False
    assert audit.capability_execution == body["capability_execution"]
    assert any(event.event_type.value == "repair_not_authorized" for event in audit.events)
    diagnosis_event = next(
        event for event in audit.events
        if event.event_type.value == "diagnosis_completed"
    )
    assert diagnosis_event.metadata["confidence"] < 0.95
    detail = client.get(f"/api/v1/recoveries/{audit.recovery_id}")
    assert detail.status_code == 200
    assert detail.json()["capability_execution"] == body["capability_execution"]
    assert detail.json()["graph_run_id"] is None
    assert detail.json()["repair_capability"] == "available"
    assert detail.json()["repair_supported"] is False
    assert detail.json()["repair_eligible"] is False
    assert detail.json()["repair_validated"] is None
    assert detail.json()["repair_authorization"] == "not_authorized"
    assert detail.json()["authorization_reason"] == body["recovery"]["authorization_reason"]


def test_authorized_external_application_enters_recovery_flow(monkeypatch):
    applications = InMemoryApplicationRepository()
    applications.upsert(ApplicationRegistration(
        ragguard_tenant_id="development",
        application_id="external-rag",
        display_name="External RAG",
        environment="production",
        knowledge_source="external_rag_api",
        query_endpoint_url="https://rag.example.test/query",
        observation_token_env_var="RAGGUARD_EXTERNAL_RAG_TOKEN",
        repair_authorized=True,
    ))
    monkeypatch.setattr(observations_route, "application_repository", applications)
    monkeypatch.setenv("RAGGUARD_EXTERNAL_RAG_TOKEN", "external-rag-token")
    def forbidden_recovery(**kwargs):
        pytest.fail("External applications require a repair adapter.")

    monkeypatch.setattr(
        observations_route.recovery_service,
        "recover",
        forbidden_recovery,
    )
    response = post_observation(
        {
            "query": "What is the retention period?",
            "retrieved_chunks": [],
            "retrieval_method": "vector",
        },
        authorization="Bearer external-rag-token",
        source_application="external-rag",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "repair_unavailable"
    assert body["recovery"]["repair_authorization"] == "authorized"
    assert body["recovery"]["authorization_source"] == "application_registration"
    assert body["recovery"]["repair_attempted"] is False
    assert body["recovery"]["repair_supported"] is False
    assert body["recovery"]["repair_eligible"] is False
    assert body["recovery"]["diagnosis"]["root_cause"] == "NO_RETRIEVAL"


@pytest.mark.parametrize(
    ("application_id", "knowledge_source", "query_endpoint"),
    [
        ("external-rag", "external_rag_api", "https://rag.example.test/query"),
        ("biomedicalrag", "observation_only", None),
    ],
)
def test_authorized_external_repair_uses_allowlisted_strategy_and_records_result(
    monkeypatch,
    configure_service_auth,
    application_id,
    knowledge_source,
    query_endpoint,
):
    source_token = "source-observation-token"
    applications = observations_route.application_repository
    applications.upsert(ApplicationRegistration(
        ragguard_tenant_id="development",
        application_id=application_id,
        display_name="External RAG" if knowledge_source == "external_rag_api" else "BiomedicalRag",
        environment="production",
        knowledge_source=knowledge_source,
        query_endpoint_url=query_endpoint,
        repair_endpoint_url="https://rag.example.test/repair",
        repair_token_env_var="RAGGUARD_EXTERNAL_REPAIR_TOKEN",
        repair_authorized=True,
        observation_token_hash=sha256(source_token.encode("utf-8")).hexdigest(),
    ))
    monkeypatch.setenv("RAGGUARD_EXTERNAL_REPAIR_TOKEN", "separate-repair-token")
    monkeypatch.setattr(
        observations_route,
        "get_supported_repairs",
        lambda _application: frozenset({RepairType.RERANK}),
    )
    monkeypatch.setattr(
        observations_route.recovery_service,
        "diagnosis_fn",
        lambda failure: DiagnosisResult(
            failure_id=failure.failure_id,
            root_cause=failure.failure_type,
            confidence=0.9,
            recommended_repairs=[RepairType.RERANK, RepairType.RECHUNK],
        ),
    )
    calls = []

    def execute(application, observation, *, failure_type, strategy):
        calls.append((application, observation, failure_type, strategy))
        return ExternalRepairResult(
            contract_version="v1",
            request_id=observation.request_id,
            strategy=strategy.value,
            status="promoted",
            validated=True,
            context_verified=True,
            improvement=0.15,
        )

    monkeypatch.setattr(observations_route, "request_external_repair", execute)
    response = post_observation(
        {
            "query": "What is the retention period?",
            "request_id": "request-123",
            "retrieved_chunks": [],
            "answer": "Keep the record for seven years.",
        },
        authorization=f"Bearer {source_token}",
        source_application=application_id,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "promoted"
    assert body["recovery"]["repair_attempted"] is True
    assert body["recovery"]["repair_validated"] is True
    assert body["recovery"]["attempts"] == [{
        "strategy": "RERANK",
        "status": "promoted",
        "improvement": 0.15,
    }]
    application, observed, failure_type, strategy = calls[0]
    assert application.repair_token_env_var == "RAGGUARD_EXTERNAL_REPAIR_TOKEN"
    assert observed.answer == "Keep the record for seven years."
    assert failure_type == "NO_RETRIEVAL"
    assert strategy == RepairType.RERANK
    audit = observations_route.recovery_repository.get(body["recovery"]["recovery_id"])
    assert audit is not None
    assert audit.final_status == "promoted"
    assert audit.attempts[0]["strategy"] == "RERANK"


def test_observations_source_application_must_match_authentication():
    response = post_observation(
        {
            "query": "What payment methods are supported?",
            "retrieved_chunks": [],
        },
        source_application="untrusted-app",
    )

    assert response.status_code == 403


def test_development_service_auth_resolves_configured_tenant(monkeypatch):
    monkeypatch.setenv("RAGGUARD_SERVICE_TOKEN", "test-service-token")
    monkeypatch.setenv("RAGGUARD_SERVICE_APPLICATION", "trustassist")
    monkeypatch.setenv("RAGGUARD_SERVICE_TENANT", "development")

    settings = load_settings("configs/development.yaml")
    authenticated_service = authenticate_service(
        "Bearer test-service-token",
        settings,
    )

    assert authenticated_service.application_id == "trustassist"
    assert authenticated_service.tenant_context.tenant_id == "development"
