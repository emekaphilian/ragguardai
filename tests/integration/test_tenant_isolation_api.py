from fastapi.testclient import TestClient

from ragguard.api.app import app
from ragguard.api.runtime import workspace
from ragguard.auth.tenant_context import TenantContext
from ragguard.common.schemas import Document
from ragguard.config import Settings
from ragguard.tenants.models import TenantPolicy
from ragguard.tenants.service import TenantService

client = TestClient(app)


def test_unknown_tenant_is_rejected():
    response = client.post(
        "/api/v1/query",
        headers={
            "X-RAGGuard-Tenant": "does-not-exist",
        },
        json={
            "query": "How do I request a refund?",
            "top_k": 5,
            "method": "hybrid",
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Unknown tenant"
    }


def test_tenant_cannot_retrieve_another_tenants_document():
    settings = Settings(
        tenant_policies=(
            TenantPolicy(
                tenant_id="tenant-a",
                application_id="app-a",
                environment="test",
                vector_namespace="namespace-a",
            ),
            TenantPolicy(
                tenant_id="tenant-b",
                application_id="app-b",
                environment="test",
                vector_namespace="namespace-b",
            ),
        )
    )

    service = TenantService(settings)

    tenant_a = service.resolve("tenant-a")
    tenant_b = service.resolve("tenant-b")

    workspace.documents = {}
    workspace.ingest_documents(
        [
            Document(
                document_id="tenant-a-doc",
                text="Tenant A confidential refund policy.",
                metadata={"source": "tenant-a-policy"},
            )
        ],
        context=tenant_a,
    )

    workspace.ingest_documents(
        [
            Document(
                document_id="tenant-b-doc",
                text="Tenant B confidential payment policy.",
                metadata={"source": "tenant-b-policy"},
            )
        ],
        context=tenant_b,
    )

    tenant_a_documents = workspace.document_rows(tenant_a)
    tenant_b_documents = workspace.document_rows(tenant_b)

    assert [doc["id"] for doc in tenant_a_documents] == ["tenant-a-doc"]
    assert [doc["id"] for doc in tenant_b_documents] == ["tenant-b-doc"]

    tenant_b_result = workspace.query(
        "Tenant A confidential refund policy",
        top_k=5,
        method="vector",
        context=tenant_b,
    )

    assert all(
        source["document_id"] != "tenant-a-doc"
        for source in tenant_b_result["sources"]
    )