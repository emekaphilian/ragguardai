from fastapi.testclient import TestClient
import pytest

from ragguard.auth.service_auth import authenticate_service
from ragguard.api.app import app
from ragguard.api.routes import observations as observations_route
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
):
    request_body = {
        "contract_version": "v1",
        "source": {
            "application_id": source_application,
            "environment": "production",
        },
        **payload,
    }
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
    records = configure_service_auth.list()
    assert len(records) == 1
    assert records[0].status == "healthy"
    assert records[0].ragguard_tenant_id == "development"
    assert records[0].application_id == "trustassist"
    assert records[0].query == "What payment methods are supported?"
    assert records[0].evaluation["status"] == "HEALTHY"
    assert records[0].failure is None
    assert records[0].recovery is None


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
    records = configure_service_auth.list()
    assert len(records) == 1
    assert records[0].status == body["status"]
    assert records[0].failure["failure_type"] == "NO_RETRIEVAL"
    assert records[0].recovery["status"] == body["recovery"]["status"]


def test_failed_observation_is_saved_if_recovery_raises(
    configure_service_auth,
    monkeypatch,
):
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


def test_observation_source_contract_has_no_tenant_id():
    from ragguard.evaluation.live import ObservationSource

    assert set(ObservationSource.model_fields) == {"application_id", "environment"}


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
    assert body["recovery"]["repair_authorization"] == "not_authorized"
    assert body["recovery"]["repair_attempted"] is False
    assert body["recovery"]["authorization_source"] == "application_registration"
    assert "has not authorized" in body["recovery"]["authorization_reason"]
    saved_observation = observations_route.observation_repository.list()[0]
    assert saved_observation.recovery == body["recovery"]
    audit = observations_route.recovery_repository.get(body["recovery"]["recovery_id"])
    assert audit is not None
    assert audit.graph_run_id is None
    assert audit.final_status == "repair_not_authorized"
    assert audit.repair_attempted is False
    assert any(event.event_type.value == "repair_not_authorized" for event in audit.events)
    detail = client.get(f"/api/v1/recoveries/{audit.recovery_id}")
    assert detail.status_code == 200
    assert detail.json()["graph_run_id"] is None
    assert detail.json()["repair_capability"] == "available"
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
    recovered = {}

    def recover(**kwargs):
        recovered.update(kwargs)
        return {
            "status": "escalated",
            "recovery_id": "authorized-external-recovery",
            "graph_run_id": "authorized-external-graph",
            "failure_event": kwargs["failure_event"],
            "repair_attempts": [],
            "completed_nodes": ["diagnose"],
            "escalation_reason": "No applicable repair strategy.",
        }

    monkeypatch.setattr(observations_route.recovery_service, "recover", recover)
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
    assert recovered
    assert body["status"] == "escalated"
    assert body["recovery"]["repair_authorization"] == "authorized"
    assert body["recovery"]["authorization_source"] == "application_registration"
    assert body["recovery"]["repair_attempted"] is False


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
