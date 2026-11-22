import pytest

from ragguard.auth.tenant_context import TenantContext
from ragguard.common.schemas import Chunk
from ragguard.retrieval.retriever import retrieve
from ragguard.storage.vector_store import VectorStore
from ragguard.api.runtime import Workspace
from ragguard.persistence.workspace_repository import InMemoryWorkspaceRepository
from ragguard.common.schemas import Document
from ragguard.auth.application_access import require_application_role
from ragguard.auth.application_access import resolve_application_context


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


def test_namespace_tfidf_scores_do_not_change_when_another_namespace_grows():
    store = VectorStore()
    store.add([Chunk(chunk_id="a", document_id="a", text="refund policy thirty days")], namespace="a")
    initial = store.search("refund policy", namespace="a").scores
    store.add([Chunk(chunk_id="b", document_id="b", text="refund refund refund policy policy policy unrelated terms")], namespace="b")
    assert store.search("refund policy", namespace="a").scores == initial


def test_same_document_id_is_independent_across_application_identity(tmp_path):
    repository = InMemoryWorkspaceRepository()
    workspace = Workspace(tmp_path / "raw", tmp_path / "recycle", repository=repository)
    app_a = TenantContext("tenant", "app-a", "staging", None, (), "ns-a", "v1", "v1")
    app_b = TenantContext("tenant", "app-b", "staging", None, (), "ns-b", "v1", "v1")
    workspace.ingest_documents([Document(document_id="shared-id", text="alpha application source")], app_a)
    workspace.ingest_documents([Document(document_id="shared-id", text="beta application source")], app_b)
    assert [row["id"] for row in workspace.document_rows(app_a)] == ["shared-id"]
    assert [row["id"] for row in workspace.document_rows(app_b)] == ["shared-id"]
    assert workspace.query("alpha application source", method="vector", context=app_a)["sources"][0]["text"].find("alpha") >= 0
    app_b_sources = workspace.query("alpha application source", method="vector", context=app_b)["sources"]
    assert app_b_sources and all("alpha" not in source["text"] for source in app_b_sources)


def test_application_role_is_checked_for_the_exact_target_scope():
    user = TenantContext(
        "tenant", "app-a", "staging", "user", ("reader",), "ns-a", "v1", "v1",
        application_memberships=(("app-a", "staging", ("operator",)), ("app-b", "staging", ("reader",))),
    )
    assert require_application_role(user, "app-a", "staging", {"operator", "admin"})
    assert not require_application_role(user, "app-b", "staging", {"operator", "admin"})
    assert not require_application_role(user, "app-a", "production", {"operator", "admin"})


def test_application_resolution_rejects_ungranted_application_and_environment():
    from ragguard.observability.application_repository import InMemoryApplicationRepository
    from ragguard.tenants.application_registration import ApplicationRegistration

    repository = InMemoryApplicationRepository()
    for application_id in ("app-a", "app-b", "app-c"):
        repository.upsert(ApplicationRegistration(
            ragguard_tenant_id="tenant", application_id=application_id,
            display_name=application_id, environment="staging",
            knowledge_source="observation_only",
        ))
    user = TenantContext(
        "tenant", "app-a", "staging", "user", ("reader",), "ns-a", "v1", "v1",
        application_memberships=(("app-a", "staging", ("operator",)), ("app-b", "staging", ("reader",))),
    )
    context_a, registration_a = resolve_application_context(user, repository, "app-a", "staging")
    assert context_a.application_id == registration_a.application_id == "app-a"
    context_b, registration_b = resolve_application_context(user, repository, "app-b", "staging")
    assert context_b.application_id == registration_b.application_id == "app-b"
    assert resolve_application_context(user, repository, "app-c", "staging") == (None, None)
    assert resolve_application_context(user, repository, "app-a", "production") == (None, None)


def test_two_workspace_instances_refresh_shared_repository_state(tmp_path):
    from threading import RLock
    from ragguard.persistence.workspace_repository import PostgreSQLWorkspaceRepository

    class SharedRepository(PostgreSQLWorkspaceRepository):
        rows = {}
        lock = RLock()
        def list_documents(self, *, include_recycled=False):
            with self.lock:
                return [row for row in self.rows.values() if include_recycled or not row[1]]
        def save_document(self, document, *, recycled=False, source_relative_path=None):
            with self.lock:
                self.rows[self._key(document)] = (document, recycled, source_relative_path)
        def save_documents(self, documents):
            with self.lock:
                for document in documents:
                    self.rows[self._key(document)] = (document, False, None)
        def delete_document(self, identity):
            with self.lock:
                return self.rows.pop(identity, None) is not None
        activity = {"runs": [], "failures": [], "repairs": []}
        def append_activity(self, kind, value):
            with self.lock:
                self.activity[kind].insert(0, value)
        def list_activity(self, kind):
            with self.lock:
                return list(self.activity[kind])
        def clear_activity(self, kind=None):
            with self.lock:
                kinds = (kind,) if kind else tuple(self.activity)
                counts = {name: len(self.activity[name]) for name in kinds}
                for name in kinds:
                    self.activity[name].clear()
                return counts
        @staticmethod
        def _key(document):
            md = document.metadata
            return (md["ragguard_tenant_id"], md["application_id"], md["environment"], document.document_id)

    SharedRepository.rows = {}
    SharedRepository.activity = {"runs": [], "failures": [], "repairs": []}
    first = Workspace(tmp_path / "raw-a", tmp_path / "recycle-a", repository=SharedRepository())
    second = Workspace(tmp_path / "raw-b", tmp_path / "recycle-b", repository=SharedRepository())
    app = TenantContext("tenant", "app", "staging", None, (), "ns", "v1", "v1")
    first.ingest_documents([Document(document_id="persisted", text="shared worker document")], app)
    second.refresh()
    assert [row["id"] for row in second.document_rows(app)] == ["persisted"]

    # Model a worker dying after the repository commits but before the local
    # index swap completes. A fresh worker must rebuild from committed rows.
    def crash_before_index_update():
        raise RuntimeError("simulated worker crash after commit")

    first._rebuild_index = crash_before_index_update
    with pytest.raises(RuntimeError, match="after commit"):
        first.ingest_documents([Document(document_id="committed-before-crash", text="recoverable committed document")], app)
    assert any(document.document_id == "committed-before-crash" for document, _, _ in SharedRepository.rows.values())
    recovered = Workspace(tmp_path / "raw-c", tmp_path / "recycle-c", repository=SharedRepository())
    recovered.refresh()
    result = recovered.query("recoverable committed document", method="vector", context=app)
    assert any(source["document_id"] == "committed-before-crash" for source in result["sources"])


def test_failed_batch_ingestion_keeps_workspace_and_repository_unchanged(tmp_path):
    class RejectingRepository(InMemoryWorkspaceRepository):
        def save_documents(self, documents):
            if any(document.document_id == "reject" for document in documents):
                raise RuntimeError("simulated transaction failure")
            super().save_documents(documents)

    repository = RejectingRepository()
    workspace = Workspace(tmp_path / "raw", tmp_path / "recycle", repository=repository)
    app = TenantContext("tenant", "app", "staging", None, (), "namespace", "v1", "v1")
    workspace.ingest_documents([Document(document_id="existing", text="original content")], app)
    previous_chunks = [(chunk.chunk_id, chunk.text) for chunk in workspace.store.chunks]
    with pytest.raises(RuntimeError, match="simulated transaction failure"):
        workspace.ingest_documents([
            Document(document_id="would-be-partial", text="new content"),
            Document(document_id="reject", text="trigger failure"),
        ], app)
    assert ("tenant", "app", "staging", "would-be-partial") not in workspace.documents
    assert [(chunk.chunk_id, chunk.text) for chunk in workspace.store.chunks] == previous_chunks
    assert all(document.document_id != "would-be-partial" for document, _, _ in repository.list_documents())
