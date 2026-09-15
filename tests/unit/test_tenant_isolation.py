from ragguard.auth.tenant_context import TenantContext
from ragguard.common.schemas import Chunk
from ragguard.retrieval.retriever import retrieve
from ragguard.storage.vector_store import VectorStore


def context(tenant_id: str) -> TenantContext:
    return TenantContext(tenant_id, tenant_id, "test", None, (), tenant_id, "v1", "v1")


def test_retrieval_only_returns_the_context_namespace():
    store = VectorStore()
    store.add([Chunk(chunk_id="a", document_id="a", text="Tenant A secret")], namespace="a")
    store.add([Chunk(chunk_id="b", document_id="b", text="Tenant B secret")], namespace="b")

    result = retrieve(store, "secret", method="hybrid", context=context("a"))

    assert [document.chunk_id for document in result.documents] == ["a"]


def test_unknown_namespace_has_no_results():
    store = VectorStore()
    store.add([Chunk(chunk_id="a", document_id="a", text="Tenant A secret")], namespace="a")

    assert retrieve(store, "secret", context=context("missing")).documents == []
