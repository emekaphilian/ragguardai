from fastapi.testclient import TestClient

from ragguard.api.app import app
from ragguard.api.runtime import workspace
from ragguard.api.routes import retrieval as retrieval_routes
from ragguard.auth.tenant_context import TenantContext
from ragguard.common.exceptions import RetrievalError
from ragguard.observability.application_repository import InMemoryApplicationRepository
from ragguard.tenants.application_registration import ApplicationRegistration

client = TestClient(app)


def test_query_retrieval_error_returns_structured_http_response(monkeypatch):
    repository = InMemoryApplicationRepository()
    repository.upsert(
        ApplicationRegistration(
            ragguard_tenant_id="tenant-a",
            application_id="default-app",
            display_name="Default App",
            environment="production",
            knowledge_source="managed_index",
            vector_namespace="default-index",
            observation_token_env_var="TEST_OBSERVATION_TOKEN",
        )
    )

    context = TenantContext(
        tenant_id="tenant-a",
        application_id="default-app",
        environment="production",
        user_id=None,
        roles=(),
        vector_namespace="default-index",
        policy_version="v1",
        index_version="v1",
    )

    monkeypatch.setattr(retrieval_routes, "application_repository", repository)
    monkeypatch.setattr(
        "ragguard.api.app.resolve_request_context",
        lambda request: context,
    )

    def failing_query(*args, **kwargs):
        raise RetrievalError("Retrieval failed.")

    monkeypatch.setattr(workspace, "query", failing_query)

    response = client.post(
        "/api/v1/query",
        json={
            "query": "Test retrieval failure",
            "top_k": 5,
            "method": "vector",
            "application_id": "default-app",
            "environment": "production",
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "RETRIEVAL_ERROR",
            "message": "Retrieval failed.",
        }
    }
