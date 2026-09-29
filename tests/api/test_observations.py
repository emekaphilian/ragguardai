from fastapi.testclient import TestClient
import pytest

from ragguard.auth.service_auth import authenticate_service
from ragguard.api.app import app
from ragguard.config import ServiceAuthSettings, Settings, load_settings
from ragguard.tenants.models import TenantPolicy

client = TestClient(app)


@pytest.fixture(autouse=True)
def configure_service_auth(monkeypatch):
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


def test_observations_healthy_retrieval():
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


def test_observations_no_retrieval():
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
