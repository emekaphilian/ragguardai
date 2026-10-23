import json
from dataclasses import replace
from hashlib import sha256

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
from ragguard.config import ServiceAuthSettings, Settings
from ragguard.observability.application_repository import InMemoryApplicationRepository
from ragguard.observability.observation_repository import InMemoryObservationRepository
from ragguard.observability.observation_activity import ObservationRecord
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
    observations = InMemoryObservationRepository()
    monkeypatch.setattr(application_routes, "observation_repository", observations)
    monkeypatch.setattr(
        "ragguard.api.app.resolve_request_context",
        lambda request: tenant_context(),
    )

    response = client.get("/api/v1/applications")

    assert response.status_code == 200
    assert response.json() == [{
        "ragguard_tenant_id": "tenant-a",
        "application_id": "support",
        "display_name": "Customer Support",
        "environment": "production",
        "knowledge_source": "external_rag_api",
        "active": True,
        "queryable": True,
        "observation_enabled": True,
        "context_verification_authorized": False,
        "independent_verification_authorized": False,
        "repair_authorized": False,
        "connection_status": "waiting_for_data",
        "last_observed_at": None,
        "last_evaluation_status": None,
    }]
    assert "SUPPORT_QUERY_TOKEN" not in response.text
    assert "SUPPORT_OBSERVATION_TOKEN" not in response.text

    observations.save(ObservationRecord.create(
        ragguard_tenant_id="tenant-a",
        application_id="support",
        status="HEALTHY",
        query="redacted",
        evaluation={},
        observation={"source": {"environment": "production"}},
        failure=None,
        recovery=None,
    ))
    connected = client.get("/api/v1/applications").json()[0]
    assert connected["connection_status"] == "connected"
    assert connected["last_observed_at"]
    assert connected["repair_authorized"] is False


def test_external_query_is_blocked_without_independent_verification_capability(
    monkeypatch,
):
    repository = InMemoryApplicationRepository()
    repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="support",
        display_name="Support",
        environment="production",
        knowledge_source="external_rag_api",
        query_endpoint_url="https://support.example.test/query",
        independent_verification_authorized=False,
    ))
    monkeypatch.setattr(retrieval_routes, "application_repository", repository)
    monkeypatch.setattr(
        "ragguard.api.app.resolve_request_context",
        lambda request: tenant_context(),
    )
    queried = []
    monkeypatch.setattr(
        retrieval_routes,
        "query_external_application",
        lambda *args, **kwargs: queried.append((args, kwargs)),
    )

    response = client.post(
        "/api/v1/query",
        json={
            "query": "What is the refund policy?",
            "application_id": "support",
            "environment": "production",
        },
    )

    assert response.status_code == 403
    assert "not authorized to independently query" in response.json()["detail"]
    assert response.json()["capability_execution"]["independent_verification"] == {
        "authorization": "not_authorized",
        "performed": False,
        "reason": "application_not_authorized",
    }
    assert queried == []


def test_external_query_runs_when_independent_verification_is_authorized(
    monkeypatch,
):
    repository = InMemoryApplicationRepository()
    repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="support",
        display_name="Support",
        environment="production",
        knowledge_source="external_rag_api",
        query_endpoint_url="https://support.example.test/query",
        independent_verification_authorized=True,
    ))
    monkeypatch.setattr(retrieval_routes, "application_repository", repository)
    monkeypatch.setattr(
        "ragguard.api.app.resolve_request_context",
        lambda request: tenant_context(),
    )
    queried = []

    def query_application(application, **kwargs):
        queried.append((application.application_id, kwargs["query"]))
        return {
            "answer": "Refunds are available within 30 days.",
            "rag_status": "retrieved",
            "retrieval_quality": {},
            "capability_execution": {
                "context_verification": {
                    "authorization": "not_authorized",
                    "performed": False,
                    "reason": "application_not_authorized",
                },
                "independent_verification": {
                    "authorization": "authorized",
                    "performed": True,
                    "reason": None,
                },
                "repair": {
                    "authorization": "not_authorized",
                    "performed": False,
                    "reason": "application_not_authorized",
                },
            },
        }

    monkeypatch.setattr(
        retrieval_routes,
        "query_external_application",
        query_application,
    )

    response = client.post(
        "/api/v1/query",
        json={
            "query": "What is the refund policy?",
            "application_id": "support",
            "environment": "production",
        },
    )

    assert response.status_code == 200
    assert queried == [("support", "What is the refund policy?")]
    assert response.json()["capability_execution"]["independent_verification"] == {
        "authorization": "authorized",
        "performed": True,
        "reason": None,
    }


def test_external_context_faithfulness_requires_context_verification_capability(
    monkeypatch,
):
    import json

    from ragguard.api.external_query import query_external_application

    body = json.dumps({
        "contract_version": "v1",
        "answer": "Refunds are available within 30 days.",
        "retrieved_chunks": [{
            "id": "refund-policy",
            "score": 0.9,
            "text": "Refunds are available within 30 days.",
        }],
        "retrieval_method": "vector",
    }).encode()

    class FakeResponse:
        is_redirect = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield body

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(external_query, "_validate_public_endpoint", lambda _url: None)
    monkeypatch.setattr(external_query.httpx, "Client", FakeClient)

    results = {}
    for authorized in (False, True):
        application = ApplicationRegistration(
            ragguard_tenant_id="tenant-a",
            application_id="support",
            display_name="Support",
            environment="production",
            knowledge_source="external_rag_api",
            query_endpoint_url="https://support.example.test/query",
            context_verification_authorized=authorized,
        )
        result = query_external_application(
            application,
            query="What is the refund policy?",
            top_k=5,
            method="vector",
        )
        results[authorized] = result["retrieval_quality"]["faithfulness"]
        if authorized:
            assert result["capability_execution"]["context_verification"] == {
                "authorization": "authorized",
                "performed": True,
                "reason": None,
            }

    assert results[False] is None
    assert results[True] == 1.0


def test_managed_context_faithfulness_requires_context_verification_capability(
    monkeypatch, tmp_path,
):
    from ragguard.api.runtime import Workspace

    repository = InMemoryApplicationRepository()
    isolated_workspace = Workspace(
        raw_directory=tmp_path / "empty-raw",
        recycle_directory=tmp_path / "empty-recycle",
    )
    isolated_workspace.ingest_documents(
        [Document(
            document_id="refund-policy",
            text="Refund policy: you may request a refund within 30 days.",
            metadata={"source": "refund-policy"},
        )],
        context=tenant_context(),
    )
    monkeypatch.setattr(retrieval_routes, "application_repository", repository)
    monkeypatch.setattr(retrieval_routes, "workspace", isolated_workspace)
    monkeypatch.setattr("ragguard.api.runtime.application_repository", repository)
    monkeypatch.setattr(
        "ragguard.api.app.resolve_request_context",
        lambda request: tenant_context(),
    )

    scores = {}
    for authorized in (False, True):
        repository.upsert(ApplicationRegistration(
            ragguard_tenant_id="tenant-a",
            application_id="managed-support",
            display_name="Managed Support",
            environment="production",
            knowledge_source="managed_index",
            vector_namespace="default-index",
            context_verification_authorized=authorized,
        ))
        response = client.post(
            "/api/v1/query",
            json={
                "query": "How do I request a refund?",
                "application_id": "managed-support",
                "environment": "production",
                "record_run": False,
            },
        )
        assert response.status_code == 200
        body = response.json()
        scores[authorized] = body["retrieval_quality"]["faithfulness"]
        assert body["capability_execution"]["context_verification"]["authorization"] == (
            "authorized" if authorized else "not_authorized"
        )

    assert scores[False] is None
    assert isinstance(scores[True], float)


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
        "repair_endpoint_url": "https://legal.example.test/repair",
        "repair_token_env_var": "LEGAL_REPAIR_TOKEN",
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
    assert "LEGAL_REPAIR_TOKEN" not in response.text
    assert repository.get("tenant-a", "legalbot", "production") is not None
    assert repository.get("tenant-a", "legalbot", "production").repair_endpoint_url == "https://legal.example.test/repair"
    assert repository.get("tenant-a", "legalbot", "production").repair_token_env_var == "LEGAL_REPAIR_TOKEN"


def test_guided_onboarding_registers_observation_app_and_issues_hash_backed_token(monkeypatch):
    repository = InMemoryApplicationRepository()
    monkeypatch.setattr(admin_routes, "application_repository", repository)
    monkeypatch.setattr(
        admin_routes,
        "load_settings",
        lambda: Settings(
            tenant_policies=(TenantPolicy(
                tenant_id="tenant-a",
                application_id="default-app",
                environment="development",
                vector_namespace="default-index",
            ),),
            service_auth=ServiceAuthSettings(tenant_id="tenant-a"),
        ),
    )
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-test-token")
    payload = {
        "application_id": "biomedicalrag",
        "display_name": "BiomedicalRag",
        "environment": "development",
    }

    denied = client.post("/api/v1/admin/applications/onboard", json=payload)
    created = client.post(
        "/api/v1/admin/applications/onboard",
        json=payload,
        headers={"Authorization": "Bearer admin-test-token"},
    )

    assert denied.status_code == 401
    assert created.status_code == 201
    body = created.json()
    token = body["observation_credential"]
    registration = repository.get("tenant-a", "biomedicalrag", "development")
    assert registration is not None
    assert registration.knowledge_source == "observation_only"
    assert registration.repair_authorized is False
    assert registration.observation_token_hash
    assert token not in registration.observation_token_hash
    assert "observation_token_hash" not in created.text
    assert "Copy this credential now" in body["credential_notice"]

    authenticated = authenticate_service(
        f"Bearer {token}",
        Settings(tenant_policies=(TenantPolicy(
            tenant_id="tenant-a",
            application_id="default-app",
            environment="development",
            vector_namespace="default-index",
        ),)),
        application_id="biomedicalrag",
        environment="development",
        application_repository=repository,
    )
    assert authenticated.tenant_context.tenant_id == "tenant-a"
    assert authenticated.registration is not None
    assert authenticated.registration.repair_authorized is False

    duplicate = client.post(
        "/api/v1/admin/applications/onboard",
        json=payload,
        headers={"Authorization": "Bearer admin-test-token"},
    )
    assert duplicate.status_code == 409


def test_guided_onboarding_rotates_credential_once_and_invalidates_old_token(monkeypatch):
    repository = InMemoryApplicationRepository()
    application = ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="supportbot",
        display_name="Support Bot",
        environment="production",
        knowledge_source="observation_only",
        observation_token_hash=sha256(b"old-token").hexdigest(),
    )
    repository.upsert(application)
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

    response = client.post(
        "/api/v1/admin/applications/tenant-a/supportbot/production/observation-credential",
        headers={"Authorization": "Bearer admin-test-token"},
    )

    assert response.status_code == 200
    token = response.json()["observation_credential"]
    updated = repository.get("tenant-a", "supportbot", "production")
    assert updated is not None
    assert updated.observation_token_hash != sha256(b"old-token").hexdigest()
    assert authenticate_service(
        f"Bearer {token}",
        Settings(tenant_policies=(TenantPolicy(
            tenant_id="tenant-a",
            application_id="default-app",
            environment="production",
            vector_namespace="default-index",
        ),)),
        application_id="supportbot",
        environment="production",
        application_repository=repository,
    ).application_id == "supportbot"
    try:
        authenticate_service(
            "Bearer old-token",
            Settings(tenant_policies=(TenantPolicy(
                tenant_id="tenant-a",
                application_id="default-app",
                environment="production",
                vector_namespace="default-index",
            ),)),
            application_id="supportbot",
            environment="production",
            application_repository=repository,
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("Credential rotation must invalidate the prior token")


def test_application_registration_update_preserves_authorization_state(monkeypatch):
    repository = InMemoryApplicationRepository()
    repository.upsert(
        ApplicationRegistration(
            ragguard_tenant_id="tenant-a",
            application_id="authorized-app",
            display_name="Authorized App",
            environment="production",
            knowledge_source="external_rag_api",
            query_endpoint_url="https://authorized.example.test/query",
            query_token_env_var="AUTHORIZED_QUERY_TOKEN",
            observation_token_env_var="AUTHORIZED_OBSERVATION_TOKEN",
            repair_authorized=False,
            context_verification_authorized=True,
            independent_verification_authorized=True,
        )
    )

    monkeypatch.setattr(admin_routes, "application_repository", repository)
    monkeypatch.setattr(
        admin_routes,
        "load_settings",
        lambda: Settings(
            tenant_policies=(
                TenantPolicy(
                    tenant_id="tenant-a",
                    application_id="default-app",
                    environment="production",
                    vector_namespace="default-index",
                ),
            )
        ),
    )
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-test-token")

    response = client.put(
        "/api/v1/admin/applications",
        json={
            "ragguard_tenant_id": "tenant-a",
            "application_id": "authorized-app",
            "display_name": "Authorized App Updated",
            "environment": "production",
            "knowledge_source": "external_rag_api",
            "query_endpoint_url": "https://authorized.example.test/query-v2",
            "query_token_env_var": "AUTHORIZED_QUERY_TOKEN",
            "observation_token_env_var": "AUTHORIZED_OBSERVATION_TOKEN",
        },
        headers={"Authorization": "Bearer admin-test-token"},
    )

    assert response.status_code == 200

    application = repository.get(
        "tenant-a",
        "authorized-app",
        "production",
        active_only=False,
    )

    assert application is not None
    assert application.display_name == "Authorized App Updated"
    assert application.repair_authorized is False
    assert application.context_verification_authorized is True
    assert application.independent_verification_authorized is True


def test_application_capability_update_requires_admin(monkeypatch):
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-test-token")

    response = client.patch(
        "/api/v1/admin/applications/tenant-a/app/production/capabilities",
        json={
            "context_verification_authorized": True,
            "independent_verification_authorized": False,
            "repair_authorized": False,
        },
    )

    assert response.status_code == 401


def test_application_capability_update_returns_not_found(monkeypatch):
    monkeypatch.setattr(admin_routes, "application_repository", InMemoryApplicationRepository())
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-test-token")

    response = client.patch(
        "/api/v1/admin/applications/tenant-a/missing/production/capabilities",
        json={
            "context_verification_authorized": False,
            "independent_verification_authorized": False,
            "repair_authorized": False,
        },
        headers={"Authorization": "Bearer admin-test-token"},
    )

    assert response.status_code == 404


def test_application_capability_update_changes_only_authorization(monkeypatch):
    repository = InMemoryApplicationRepository()
    original = ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="trustassist",
        display_name="TrustAssist",
        environment="production",
        knowledge_source="external_rag_api",
        query_endpoint_url="https://trustassist.example.test/query",
        query_token_env_var="TRUSTASSIST_QUERY_TOKEN",
        observation_token_env_var="TRUSTASSIST_OBSERVATION_TOKEN",
        repair_authorized=False,
        context_verification_authorized=False,
        independent_verification_authorized=False,
    )
    repository.upsert(original)
    monkeypatch.setattr(admin_routes, "application_repository", repository)
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-test-token")
    url = "/api/v1/admin/applications/tenant-a/trustassist/production/capabilities"
    headers = {"Authorization": "Bearer admin-test-token"}

    first = client.patch(
        url,
        json={
            "context_verification_authorized": True,
            "independent_verification_authorized": False,
            "repair_authorized": False,
        },
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["context_verification_authorized"] is True
    assert first.json()["independent_verification_authorized"] is False
    assert first.json()["repair_authorized"] is False

    second = client.patch(
        url,
        json={
            "context_verification_authorized": False,
            "independent_verification_authorized": True,
            "repair_authorized": False,
        },
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["context_verification_authorized"] is False
    assert second.json()["independent_verification_authorized"] is True
    assert second.json()["repair_authorized"] is False

    application = repository.get(
        "tenant-a",
        "trustassist",
        "production",
        active_only=False,
    )
    assert application is not None
    assert application.display_name == original.display_name
    assert application.knowledge_source == original.knowledge_source
    assert application.query_endpoint_url == original.query_endpoint_url
    assert application.query_token_env_var == original.query_token_env_var
    assert application.observation_token_env_var == original.observation_token_env_var
    assert "TRUSTASSIST_QUERY_TOKEN" not in second.text
    assert "TRUSTASSIST_OBSERVATION_TOKEN" not in second.text

    third = client.patch(
        url,
        json={
            "context_verification_authorized": False,
            "independent_verification_authorized": True,
            "repair_authorized": True,
        },
        headers=headers,
    )
    assert third.status_code == 200
    assert third.json()["context_verification_authorized"] is False
    assert third.json()["independent_verification_authorized"] is True
    assert third.json()["repair_authorized"] is True


def test_application_capability_update_preserves_registration_configuration(
    monkeypatch,
):
    repository = InMemoryApplicationRepository()
    repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="preserve-app",
        display_name="Preserve App",
        environment="production",
        knowledge_source="external_rag_api",
        query_endpoint_url="https://source.example.test/query",
        query_token_env_var="SOURCE_QUERY_TOKEN",
        observation_token_env_var="SOURCE_OBSERVATION_TOKEN",
        active=True,
    ))
    monkeypatch.setattr(admin_routes, "application_repository", repository)
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-test-token")

    response = client.patch(
        "/api/v1/admin/applications/tenant-a/preserve-app/production/capabilities",
        json={
            "context_verification_authorized": True,
            "independent_verification_authorized": True,
            "repair_authorized": False,
        },
        headers={"Authorization": "Bearer admin-test-token"},
    )

    assert response.status_code == 200
    application = repository.get(
        "tenant-a",
        "preserve-app",
        "production",
        active_only=False,
    )
    assert application is not None
    assert application.display_name == "Preserve App"
    assert application.environment == "production"
    assert application.knowledge_source == "external_rag_api"
    assert application.query_endpoint_url == "https://source.example.test/query"
    assert application.query_token_env_var == "SOURCE_QUERY_TOKEN"
    assert application.observation_token_env_var == "SOURCE_OBSERVATION_TOKEN"
    assert application.active is True


def test_application_capability_update_keeps_repair_unauthorized_when_requested(
    monkeypatch,
):
    repository = InMemoryApplicationRepository()
    repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="no-repair-app",
        display_name="No Repair App",
        environment="production",
        knowledge_source="external_rag_api",
        query_endpoint_url="https://source.example.test/query",
        query_token_env_var="QUERY_TOKEN",
        observation_token_env_var="OBSERVATION_TOKEN",
        repair_authorized=False,
        context_verification_authorized=True,
        independent_verification_authorized=True,
    ))
    monkeypatch.setattr(admin_routes, "application_repository", repository)
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-test-token")

    response = client.patch(
        "/api/v1/admin/applications/tenant-a/no-repair-app/production/capabilities",
        json={
            "context_verification_authorized": True,
            "independent_verification_authorized": True,
            "repair_authorized": False,
        },
        headers={"Authorization": "Bearer admin-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["repair_authorized"] is False
    application = repository.get(
        "tenant-a",
        "no-repair-app",
        "production",
        active_only=False,
    )
    assert application is not None
    assert application.repair_authorized is False


def test_application_capability_update_never_returns_credentials(monkeypatch):
    repository = InMemoryApplicationRepository()
    repository.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="credential-app",
        display_name="Credential App",
        environment="production",
        knowledge_source="external_rag_api",
        query_endpoint_url="https://source.example.test/query",
        query_token_env_var="PRIVATE_QUERY_TOKEN",
        observation_token_env_var="PRIVATE_OBSERVATION_TOKEN",
    ))
    monkeypatch.setattr(admin_routes, "application_repository", repository)
    monkeypatch.setenv("RAGGUARD_ADMIN_TOKEN", "admin-test-token")

    response = client.patch(
        "/api/v1/admin/applications/tenant-a/credential-app/production/capabilities",
        json={
            "context_verification_authorized": True,
            "independent_verification_authorized": True,
            "repair_authorized": False,
        },
        headers={"Authorization": "Bearer admin-test-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "query_token_env_var" not in body
    assert "observation_token_env_var" not in body
    assert "PRIVATE_QUERY_TOKEN" not in response.text
    assert "PRIVATE_OBSERVATION_TOKEN" not in response.text
    assert body["context_verification_authorized"] is True
    assert body["independent_verification_authorized"] is True
    assert body["repair_authorized"] is False


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


def test_application_admin_requires_separate_repair_credential(monkeypatch):
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
            "query_endpoint_url": "https://external.example.test/query",
            "repair_endpoint_url": "https://external.example.test/repair",
            "observation_token_env_var": "EXTERNAL_OBSERVATION_TOKEN",
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
        independent_verification_authorized=True,
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


def test_guided_integration_endpoints_expose_setup_plan():
    methods = client.get("/api/v1/integration-methods")
    assert methods.status_code == 200
    payload = methods.json()
    assert payload
    assert any(item["id"] == "python-adapter" for item in payload)

    plan = client.post(
        "/api/v1/application-integration",
        json={
            "application_name": "BiomedicalRag",
            "framework": "python",
            "environment": "development",
            "knowledge_source": "observation_only",
            "integration_method": "python-adapter",
        },
    )
    assert plan.status_code == 200
    body = plan.json()
    assert body["application_name"] == "BiomedicalRag"
    assert body["recommended_method"]["id"] == "python-adapter"
    assert body["status"] == "setup_guidance_only"
    assert body["next_steps"]
    assert "query=query" in body["python_example"]
    assert "redacted before sending by default" in body["python_example"]
    assert "answers and document text" in body["recommended_method"]["summary"]
    assert body["suggested_application_id"] == "BiomedicalRag"
    assert "Registration: not completed by this setup plan." in body["checklist"]
    assert any("no index migration" in item for item in body["checklist"])
