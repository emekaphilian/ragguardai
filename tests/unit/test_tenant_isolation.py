import pytest

from ragguard.auth.tenant_context import ApplicationScope, TenantContext
from ragguard.common.exceptions import RetrievalError
from ragguard.common.schemas import Chunk
from ragguard.retrieval import retriever as retriever_module
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
    store.add([Chunk(chunk_id="a", document_id="a", text="Tenant A secret", metadata={
        "ragguard_tenant_id": "a", "application_id": "a", "environment": "test",
    })], namespace="a")
    store.add([Chunk(chunk_id="b", document_id="b", text="Tenant B secret", metadata={
        "ragguard_tenant_id": "b", "application_id": "b", "environment": "test",
    })], namespace="b")

    result = retrieve(store, "secret", method="hybrid", context=context("a"))

    assert [document.chunk_id for document in result.documents] == ["a"]


def test_unknown_namespace_has_no_results():
    store = VectorStore()
    store.add([Chunk(chunk_id="a", document_id="a", text="Tenant A secret")], namespace="a")

    assert retrieve(store, "secret", context=context("missing")).documents == []


def test_shared_vector_namespace_still_isolates_application_identity():
    store = VectorStore()
    store.add([
        Chunk(chunk_id="a", document_id="shared", text="alpha secret", metadata={
            "ragguard_tenant_id": "tenant", "application_id": "app-a", "environment": "staging",
        }),
        Chunk(chunk_id="b", document_id="shared", text="beta secret", metadata={
            "ragguard_tenant_id": "tenant", "application_id": "app-b", "environment": "staging",
        }),
    ], namespace="shared")
    app_a = TenantContext("tenant", "app-a", "staging", None, (), "shared", "v1", "v1")

    result = retrieve(store, "secret", method="vector", context=app_a)

    assert result.documents
    assert {document.chunk_id for document in result.documents} == {"a"}


def test_empty_application_scope_has_no_results_when_namespace_is_populated():
    store = VectorStore()
    store.add([Chunk(chunk_id="a", document_id="a", text="secret", metadata={
        "ragguard_tenant_id": "tenant", "application_id": "app-a", "environment": "staging",
    })], namespace="shared")
    empty = TenantContext("tenant", "app-b", "staging", None, (), "shared", "v1", "v1")

    assert retrieve(store, "secret", context=empty).documents == []


def test_namespace_tfidf_scores_do_not_change_when_another_namespace_grows():
    store = VectorStore()
    store.add([Chunk(chunk_id="a", document_id="a", text="refund policy thirty days")], namespace="a")
    initial = store.search_privileged("refund policy", namespace="a").scores
    store.add([Chunk(chunk_id="b", document_id="b", text="refund refund refund policy policy policy unrelated terms")], namespace="b")
    assert store.search_privileged("refund policy", namespace="a").scores == initial


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", ""),
        ("application_id", " "),
        ("environment", None),
        ("vector_namespace", ""),
    ],
)
def test_tenant_context_rejects_incomplete_application_scope(field, value):
    values = {
        "tenant_id": "tenant",
        "application_id": "app",
        "environment": "staging",
        "vector_namespace": "shared",
    }
    values[field] = value
    with pytest.raises(ValueError, match="non-empty string"):
        TenantContext(
            values["tenant_id"], values["application_id"], values["environment"],
            None, (), values["vector_namespace"], "v1", "v1",
        )


def test_application_scope_rejects_partial_and_invalid_scope():
    with pytest.raises(ValueError, match="vector_namespace"):
        ApplicationScope("tenant", "app", "staging", "")
    with pytest.raises(ValueError, match="application_id"):
        ApplicationScope("tenant", None, "staging", "shared")


def test_application_retrieval_rejects_missing_partial_and_namespace_only_scope():
    store = VectorStore()
    store.add(
        [Chunk(chunk_id="a", document_id="a", text="scoped secret", metadata={
            "ragguard_tenant_id": "tenant",
            "application_id": "app",
            "environment": "staging",
        })],
        namespace="shared",
    )
    scoped_search = getattr(store, "search")
    with pytest.raises(TypeError):
        scoped_search("secret")
    with pytest.raises(TypeError):
        scoped_search("secret", namespace="shared")
    with pytest.raises(ValueError, match="complete ApplicationScope"):
        scoped_search("secret", scope=("tenant", "app", "staging"))
    retrieve_call = getattr(retriever_module, "retrieve")
    with pytest.raises(TypeError):
        retrieve_call(store, "secret")
    with pytest.raises(RetrievalError, match="complete tenant and application context"):
        retrieve_call(store, "secret", context=None)


def test_privileged_retrieval_requires_an_explicit_namespace():
    store = VectorStore()
    with pytest.raises(TypeError):
        store.search_privileged("secret")
    with pytest.raises(ValueError, match="explicit namespace"):
        store.search_privileged("secret", namespace=" ")


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


def test_concurrent_retrieval_and_refresh_keep_application_scope_consistent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import RLock
    from ragguard.persistence.workspace_repository import PostgreSQLWorkspaceRepository

    class SharedRepository(PostgreSQLWorkspaceRepository):
        rows = []
        lock = RLock()

        def list_documents(self, *, include_recycled=False):
            with self.lock:
                return list(self.rows)

    context_a = TenantContext("tenant", "app-a", "staging", None, (), "shared", "v1", "v1")
    context_b = TenantContext("tenant", "app-b", "staging", None, (), "shared", "v1", "v1")
    SharedRepository.rows = [
        (Document(document_id="a", text="alpha private marker", metadata={
            "ragguard_tenant_id": "tenant",
            "application_id": "app-a",
            "environment": "staging",
            "tenant_namespace": "shared",
            "identity_scope_explicit": True,
        }), False, None),
        (Document(document_id="b", text="beta private marker", metadata={
            "ragguard_tenant_id": "tenant",
            "application_id": "app-b",
            "environment": "staging",
            "tenant_namespace": "shared",
            "identity_scope_explicit": True,
        }), False, None),
    ]
    workspace = Workspace(
        tmp_path / "raw",
        tmp_path / "recycle",
        repository=SharedRepository(),
    )
    workspace.refresh()

    def retrieve_and_refresh(index):
        if index % 2:
            workspace.refresh()
        context = context_a if index % 2 else context_b
        marker = "alpha" if context is context_a else "beta"
        result = workspace.query(
            f"{marker} private marker",
            method="vector",
            context=context,
            record_run=False,
        )
        assert result["sources"]
        assert all(marker in source["text"] for source in result["sources"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(retrieve_and_refresh, range(40)))


def test_postgres_reload_uses_database_columns_over_conflicting_document_json(tmp_path):
    from ragguard.persistence.workspace_repository import PostgreSQLWorkspaceRepository

    tenant_id = "database-tenant"
    application_id = "database-application"
    environment = "staging"
    namespace = "database-namespace"
    document = Document(
        document_id="conflicting-ownership",
        text="database authoritative retrieval marker",
        metadata={
            "ragguard_tenant_id": "json-tenant",
            "application_id": "json-application",
            "environment": "json-environment",
            "tenant_namespace": "json-namespace",
        },
    )
    row = (
        document.model_dump(mode="json"),
        False,
        None,
        tenant_id,
        application_id,
        environment,
        namespace,
    )

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query):
            self.query = query

        def fetchall(self):
            return [row]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return Cursor()

    repository = PostgreSQLWorkspaceRepository(connection_factory=Connection)
    workspace = Workspace(
        tmp_path / "raw",
        tmp_path / "recycle",
        repository=repository,
    )
    context = TenantContext(
        tenant_id, application_id, environment, None, (), namespace, "v1", "v1"
    )
    workspace.refresh()

    retrieval = workspace.store.search(
        "database authoritative retrieval marker",
        scope=context.scope,
    )

    assert retrieval.documents
    assert all(
        (
            chunk.metadata["ragguard_tenant_id"],
            chunk.metadata["application_id"],
            chunk.metadata["environment"],
            chunk.metadata["tenant_namespace"],
        ) == (tenant_id, application_id, environment, namespace)
        for chunk in retrieval.documents
    )
