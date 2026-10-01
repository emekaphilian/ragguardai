import json
from dataclasses import replace

from fastapi.testclient import TestClient

from ragguard.api.app import app
from ragguard.api import external_query
from ragguard.api.runtime import application_repository as runtime_application_repository, workspace
from ragguard.api.routes import admin as admin_routes
from ragguard.api.routes import applications as application_routes
from ragguard.api.routes import retrieval as retrieval_routes
from ragguard.auth.service_auth import authenticate_service
from ragguard.auth.tenant_context import TenantContext
from ragguard.common.schemas import Document
from ragguard.config import Settings
from ragguard.observability.application_repository import InMemoryApplicationRepository
from ragguard.tenants.application_registration import ApplicationRegistration
from ragguard.tenants.models import TenantPolicy
from ragguard.storage.vector_store import VectorStore

client = TestClient(app)


def tenant_context():
    return TenantContext(
        tenant_id="tenant-a",
        application_id="default-app",
        environment="production",
        user_id=None,
        roles=(),
        vector_namespace="default-index",
        policy_version="v1",
        index_version="v1",
    )


def test_applications_endpoint_lists_only_current_tenant_and_public_fields(monkeypatch):
    repository = InMemoryApplicationRepository()
    repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="support",
        display_name="Customer Support",
        environment="production",
        knowledge_source="external_rag_api",
        query_endpoint_url="https://support.example.test/query",
        query_token_env_var="SUPPORT_QUERY_TOKEN",
        observation_token_env_var="SUPPORT_OBSERVATION_TOKEN",
    ))
    repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-b",
        application_id="finance",
        display_name="Finance RAG",
        environment="production",
        knowledge_source="managed_index",
        vector_namespace="finance-prod",
    ))
    monkeypatch.setattr(application_routes, "application_repository", repository)
    monkeypatch.setattr(
        "ragguard.api.app.resolve_request_context",
        lambda request: tenant_context(),
    )

    response = client.get("/api/v1/applications")

    assert response.status_code == 200
    assert response.json() == [{
        "application_id": "support",
        "display_name": "Customer Support",
        "environment": "production",
        "knowledge_source": "external_rag_api",
        "active": True,
        "queryable": True,
        "observation_enabled": True,
    }]
    assert "SUPPORT_QUERY_TOKEN" not in response.text
    assert "SUPPORT_OBSERVATION_TOKEN" not in response.text


def test_application_registration_requires_admin_and_never_returns_credentials(monkeypatch):
    repository = InMemoryApplicationRepository()
    monkeypatch.setattr(admin_routes, "application_repository", repository)
    monkeypatch.setattr(
        admin_routes,
        "load_settings",
        lambda: Settings(tenant_policies=(TenantPolicy(
            tenant_id="tenant-a",
            application_id="default-app",
            environment="production",
            vector_namespace="default-index",
        ),)),
    )
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-test-token")
    payload = {
        "ragguard_tenant_id": "tenant-a",
        "application_id": "legalbot",
        "display_name": "Legal RAG",
        "environment": "production",
        "knowledge_source": "external_rag_api",
        "query_endpoint_url": "https://legal.example.test/query",
        "query_token_env_var": "LEGAL_QUERY_TOKEN",
        "observation_token_env_var": "LEGAL_OBSERVATION_TOKEN",
    }

    unauthorized = client.put("/api/v1/admin/applications", json=payload)
    response = client.put(
        "/api/v1/admin/applications",
        json=payload,
        headers={"Authorization": "Bearer admin-test-token"},
    )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json()["application_id"] == "legalbot"
    assert response.json()["queryable"] is True
    assert "LEGAL_QUERY_TOKEN" not in response.text
    assert repository.get("tenant-a", "legalbot", "production") is not None


def test_application_admin_rejects_non_https_external_query_url(monkeypatch):
    monkeypatch.setattr(admin_routes, "application_repository", InMemoryApplicationRepository())
    monkeypatch.setattr(
        admin_routes,
        "load_settings",
        lambda: Settings(tenant_policies=(TenantPolicy(
            tenant_id="tenant-a",
            application_id="default-app",
            environment="production",
            vector_namespace="default-index",
        ),)),
    )
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-test-token")

    response = client.put(
        "/api/v1/admin/applications",
        json={
            "ragguard_tenant_id": "tenant-a",
            "application_id": "external",
            "display_name": "External RAG",
            "environment": "production",
            "knowledge_source": "external_rag_api",
            "query_endpoint_url": "http://127.0.0.1/query",
        },
        headers={"Authorization": "Bearer admin-test-token"},
    )

    assert response.status_code == 422


def test_registered_application_observation_credential_resolves_its_scope(monkeypatch):
    repository = InMemoryApplicationRepository()
    repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="customerbot",
        display_name="Customer Bot",
        environment="production",
        knowledge_source="observation_only",
        observation_token_env_var="CUSTOMERBOT_OBSERVATION_TOKEN",
    ))
    monkeypatch.setenv("CUSTOMERBOT_OBSERVATION_TOKEN", "app-specific-token")
    settings = Settings(tenant_policies=(TenantPolicy(
        tenant_id="tenant-a",
        application_id="tenant-default",
        environment="production",
        vector_namespace="tenant-a-index",
    ),))

    authenticated = authenticate_service(
        "Bearer app-specific-token",
        settings,
        application_id="customerbot",
        environment="production",
        application_repository=repository,
    )

    assert authenticated.application_id == "customerbot"
    assert authenticated.tenant_context.tenant_id == "tenant-a"
    assert authenticated.tenant_context.application_id == "customerbot"
    assert authenticated.tenant_context.vector_namespace == "tenant-a-index"


def test_query_uses_registered_managed_index_namespace(monkeypatch):
    repository = InMemoryApplicationRepository()
    repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="legalbot",
        display_name="Legal RAG",
        environment="production",
        knowledge_source="managed_index",
        vector_namespace="legal-prod-index",
    ))
    context = tenant_context()
    legal_context = replace(
        context,
        application_id="legalbot",
        vector_namespace="legal-prod-index",
    )
    monkeypatch.setattr(retrieval_routes, "application_repository", repository)
    monkeypatch.setattr(workspace, "documents", {})
    monkeypatch.setattr(workspace, "store", VectorStore())
    workspace.ingest_documents(
        [Document(
            document_id="legal-policy",
            text="The legal retention period is ten years.",
            metadata={"source": "Legal policy"},
        )],
        context=legal_context,
    )
    monkeypatch.setattr(
        "ragguard.api.app.resolve_request_context",
        lambda request: context,
    )

    response = client.post(
        "/api/v1/query",
        json={
            "query": "What is the legal retention period?",
            "method": "vector",
            "application_id": "legalbot",
            "environment": "production",
            "record_run": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["application_id"] == "legalbot"
    assert response.json()["environment"] == "production"
    assert response.json()["knowledge_source"] == "managed_index"
    assert response.json()["sources"][0]["document_id"] == "legal-policy"


def test_query_rejects_unregistered_application(monkeypatch):
    repository = InMemoryApplicationRepository()
    repository.bootstrap((TenantPolicy(
        tenant_id="tenant-a",
        application_id="default-app",
        environment="production",
        vector_namespace="default-index",
    ),))
    monkeypatch.setattr(retrieval_routes, "application_repository", repository)
    monkeypatch.setattr(
        "ragguard.api.app.resolve_request_context",
        lambda request: tenant_context(),
    )

    response = client.post(
        "/api/v1/query",
        json={
            "query": "Should not query an unregistered target",
            "application_id": "unknown-app",
            "environment": "production",
        },
    )

    assert response.status_code == 404


def test_observation_only_application_cannot_be_queried(monkeypatch):
    repository = InMemoryApplicationRepository()
    repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="metrics-only",
        display_name="Metrics only",
        environment="production",
        knowledge_source="observation_only",
    ))
    monkeypatch.setattr(retrieval_routes, "application_repository", repository)
    monkeypatch.setattr(
        "ragguard.api.app.resolve_request_context",
        lambda request: tenant_context(),
    )

    response = client.post(
        "/api/v1/query",
        json={
            "query": "Should remain observation-only",
            "application_id": "metrics-only",
            "environment": "production",
        },
    )

    assert response.status_code == 409


def test_external_query_uses_standard_adapter_contract_and_server_secret(monkeypatch):
    repository = InMemoryApplicationRepository()
    repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="supportbot",
        display_name="Support Bot",
        environment="production",
        knowledge_source="external_rag_api",
        query_endpoint_url="https://support.example.test/v1/query",
        query_token_env_var="SUPPORTBOT_QUERY_TOKEN",
    ))
    monkeypatch.setattr(retrieval_routes, "application_repository", repository)
    monkeypatch.setattr(
        "ragguard.api.app.resolve_request_context",
        lambda request: tenant_context(),
    )
    monkeypatch.setenv("SUPPORTBOT_QUERY_TOKEN", "server-only-token")
    monkeypatch.setattr(
        external_query.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    captured = {}

    class FakeResponse:
        is_redirect = False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield json.dumps({
                "contract_version": "v1",
                "answer": "Support is available by phone and email.",
                "retrieved_chunks": [{
                    "id": "support-chunk-1",
                    "score": 0.91,
                    "text": "Contact support by phone or email.",
                }],
                "retrieval_method": "hybrid",
                "retrieval_latency_ms": 28,
                "embedding_degraded": False,
            }).encode()

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_options"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def stream(self, method, url, *, headers, json):
            captured.update(method=method, url=url, headers=headers, request=json)
            return FakeResponse()

    monkeypatch.setattr(external_query.httpx, "Client", FakeClient)

    response = client.post(
        "/api/v1/query",
        json={
            "query": "How do I contact support?",
            "method": "hybrid",
            "application_id": "supportbot",
            "environment": "production",
            "record_run": False,
        },
    )

    assert response.status_code == 200
    assert captured["method"] == "POST"
    assert captured["url"] == "https://support.example.test/v1/query"
    assert captured["headers"]["Authorization"] == "Bearer server-only-token"
    assert captured["request"] == {
        "contract_version": "v1",
        "query": "How do I contact support?",
        "top_k": 5,
        "method": "hybrid",
    }
    assert response.json()["application_id"] == "supportbot"
    assert response.json()["reliability_evaluation"]["retrieved_count"] == 1
    assert "server-only-token" not in response.text


def test_external_query_rejects_private_address(monkeypatch):
    monkeypatch.setattr(
        external_query.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )

    try:
        external_query._validate_public_endpoint("https://adapter.example.test/query")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("Private adapter addresses must be rejected")
