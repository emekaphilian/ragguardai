"""Opt-in persistence checks against an isolated PostgreSQL test database.

Set RAGGUARD_TEST_DATABASE_URL to run these restart and multi-instance checks.
Never point it at a production or shared staging database: the test cleans up
its uniquely named tenant rows after each case.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import psycopg
from psycopg import sql

from ragguard.api.runtime import Workspace
from ragguard.auth.tenant_context import TenantContext
from ragguard.common.schemas import Document
from ragguard.persistence.database import apply_migrations
from ragguard.persistence.database import connect
from ragguard.persistence.workspace_repository import PostgreSQLWorkspaceRepository
from ragguard.persistence.application_repository import PostgreSQLApplicationRepository
from ragguard.tenants.application_registration import ApplicationRegistration


DATABASE_URL = os.getenv("RAGGUARD_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RAGGUARD_TEST_DATABASE_URL is not configured")


def test_postgres_reload_uses_database_ownership_for_retrieval():
    apply_migrations(database_url=DATABASE_URL)
    tenant = f"authoritative-scope-{uuid4().hex}"
    application_id = "database-owner"
    environment = "staging"
    namespace = f"{tenant}-namespace"
    context = TenantContext(
        tenant, application_id, environment, None, (), namespace, "v1", "v1"
    )
    document = Document(
        document_id="conflicting-json-scope",
        text="database authoritative ownership retrieval marker",
        metadata={
            "ragguard_tenant_id": "json-tenant",
            "application_id": "json-application",
            "environment": "json-environment",
            "tenant_namespace": "json-namespace",
        },
    )
    repository = PostgreSQLWorkspaceRepository(DATABASE_URL)
    try:
        with connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO managed_documents
                    (ragguard_tenant_id, application_id, environment, document_id,
                     namespace, document, recycled, source_relative_path)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, false, NULL)""",
                    (
                        tenant,
                        application_id,
                        environment,
                        document.document_id,
                        namespace,
                        json.dumps(document.model_dump(mode="json")),
                    ),
                )

        loaded = next(
            item[0]
            for item in repository.list_documents()
            if item[0].document_id == document.document_id
        )
        assert loaded.metadata["ragguard_tenant_id"] == tenant
        assert loaded.metadata["application_id"] == application_id
        assert loaded.metadata["environment"] == environment
        assert loaded.metadata["tenant_namespace"] == namespace

        workspace = Workspace(repository=repository)
        workspace.refresh()
        retrieval = workspace.store.search(
            "database authoritative ownership retrieval marker",
            scope=context.scope,
        )
        assert retrieval.documents
        assert all(
            (
                chunk.metadata["ragguard_tenant_id"],
                chunk.metadata["application_id"],
                chunk.metadata["environment"],
                chunk.metadata["tenant_namespace"],
            ) == (tenant, application_id, environment, namespace)
            for chunk in retrieval.documents
        )
    finally:
        repository.delete_document(
            (tenant, application_id, environment, document.document_id)
        )


def test_postgres_workspace_documents_survive_workspace_recreation_and_isolate_scope(tmp_path):
    apply_migrations(database_url=DATABASE_URL)
    repository_a = PostgreSQLWorkspaceRepository(DATABASE_URL)
    repository_b = PostgreSQLWorkspaceRepository(DATABASE_URL)
    application_repository = PostgreSQLApplicationRepository(DATABASE_URL)
    tenant = f"workspace-test-{uuid4().hex}"
    app_names = ("trustassist", "biomedicalrag", "third-rag-app")
    contexts = {
        name: TenantContext(tenant, name, "staging", None, (), f"{tenant}-{name}", "v1", "v1")
        for name in app_names
    }
    first = Workspace(tmp_path / "raw-a", tmp_path / "recycle-a", repository=repository_a)
    second = Workspace(tmp_path / "raw-b", tmp_path / "recycle-b", repository=repository_b)
    try:
        for app_name in app_names:
            application_repository.upsert(ApplicationRegistration(
                ragguard_tenant_id=tenant, application_id=app_name,
                display_name=app_name, environment="staging",
                knowledge_source="managed_index", vector_namespace=contexts[app_name].vector_namespace,
            ))
            first.ingest_documents([Document(document_id="same-id", text=f"{app_name} only source")], contexts[app_name])
        second.refresh()
        for app_name in app_names:
            assert application_repository.get(tenant, app_name, "staging") is not None
            context = contexts[app_name]
            assert [row["id"] for row in second.document_rows(context)] == ["same-id"]
            sources = second.query(f"{app_name} only source", method="vector", context=context)["sources"]
            assert sources and all(app_name in item["text"] for item in sources)

        shared_namespace_context = TenantContext(
            tenant, "shared-namespace-app", "staging", None, (),
            contexts[app_names[0]].vector_namespace, "v1", "v1",
        )
        application_repository.upsert(ApplicationRegistration(
            ragguard_tenant_id=tenant,
            application_id=shared_namespace_context.application_id,
            display_name="shared-namespace-app",
            environment="staging",
            knowledge_source="managed_index",
            vector_namespace=shared_namespace_context.vector_namespace,
        ))
        first.ingest_documents(
            [Document(document_id="shared-namespace-doc", text="other application cross-scope marker")],
            shared_namespace_context,
        )
        trustassist_results = first.query(
            "cross-scope marker", method="vector", context=contexts[app_names[0]]
        )["sources"]
        assert all(item["document_id"] != "shared-namespace-doc" for item in trustassist_results)
        shared_app_results = first.query(
            "cross-scope marker", method="vector", context=shared_namespace_context
        )["sources"]
        assert shared_app_results
        assert all(item["document_id"] == "shared-namespace-doc" for item in shared_app_results)

        # A database error halfway through a batch must roll back all documents
        # in that batch and leave the worker's prior index intact.
        trigger_suffix = uuid4().hex[:10]
        function_name = f"fail_workspace_ingest_{trigger_suffix}"
        trigger_name = f"fail_workspace_ingest_trigger_{trigger_suffix}"
        with connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.ragguard_tenant_id = {} AND NEW.document_id = 'reject-batch' THEN RAISE EXCEPTION 'simulated ingestion failure'; END IF; RETURN NEW; END; $$").format(sql.Identifier(function_name), sql.Literal(tenant)))
                cursor.execute(sql.SQL("CREATE TRIGGER {} BEFORE INSERT OR UPDATE ON managed_documents FOR EACH ROW EXECUTE FUNCTION {}()").format(sql.Identifier(trigger_name), sql.Identifier(function_name)))
        try:
            with pytest.raises(psycopg.Error, match="simulated ingestion failure"):
                first.ingest_documents([
                    Document(document_id="would-be-partial", text="must rollback"),
                    Document(document_id="reject-batch", text="forced database rejection"),
                ], contexts[app_names[0]])
            first.refresh()
            assert (tenant, app_names[0], "staging", "would-be-partial") not in first.documents
        finally:
            with connect(DATABASE_URL) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql.SQL("DROP TRIGGER IF EXISTS {} ON managed_documents").format(sql.Identifier(trigger_name)))
                    cursor.execute(sql.SQL("DROP FUNCTION IF EXISTS {}()").format(sql.Identifier(function_name)))

        def crash_after_commit():
            raise RuntimeError("simulated worker crash after database commit")

        first._rebuild_index = crash_after_commit
        with pytest.raises(RuntimeError, match="after database commit"):
            first.ingest_documents([
                Document(document_id="committed-before-crash", text="recover after worker termination")
            ], contexts[app_names[0]])
        recovered_worker = Workspace(
            tmp_path / "restarted-worker-raw",
            tmp_path / "restarted-worker-recycle",
            repository=PostgreSQLWorkspaceRepository(DATABASE_URL),
        )
        recovered_worker.refresh()
        recovery_result = recovered_worker.query(
            "recover after worker termination", method="vector", context=contexts[app_names[0]]
        )
        assert any(source["document_id"] == "committed-before-crash" for source in recovery_result["sources"])

        # Separate workspace objects stand in for API workers. Concurrent upserts
        # and queries exercise PostgreSQL visibility and namespace isolation.
        workers = [
            Workspace(tmp_path / f"raw-{index}", tmp_path / f"recycle-{index}", repository=PostgreSQLWorkspaceRepository(DATABASE_URL))
            for index in range(6)
        ]
        tasks = [(app_name, index) for app_name in app_names for index in range(4)]

        operations = [(kind, app_name, index) for app_name, index in tasks for kind in ("ingest", "query")]

        def execute(operation):
            kind, app_name, index = operation
            marker = f"{app_name} concurrent marker {index}"
            if kind == "ingest":
                workers[index % len(workers)].ingest_documents(
                    [Document(document_id=f"concurrent-{index}", text=marker)], contexts[app_name]
                )
                return kind, app_name, []
            result = workers[(index + 1) % len(workers)].query(marker, method="vector", context=contexts[app_name])
            return kind, app_name, result["sources"]

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(execute, operations))
        query_results = [result for result in results if result[0] == "query"]
        allowed_texts = {
            app_name: {f"{app_name} only source"}
            | {f"{app_name} concurrent marker {index}" for index in range(4)}
            | ({"recover after worker termination"} if app_name == app_names[0] else set())
            for app_name in app_names
        }
        for _, app_name, sources in query_results:
            assert all(item["text"] in allowed_texts[app_name] for item in sources), (
                app_name,
                [(item["document_id"], item["text"]) for item in sources],
            )
        for app_name, index in tasks:
            final_result = second.query(
                f"{app_name} concurrent marker {index}", method="vector", context=contexts[app_name]
            )
            assert final_result["sources"]
            assert all(item["text"] in allowed_texts[app_name] for item in final_result["sources"])

        empty_context = TenantContext(tenant, "empty-app", "staging", None, (), f"{tenant}-empty-app", "v1", "v1")
        assert second.query("concurrent marker", method="vector", context=empty_context)["sources"] == []

        def refresh_and_query(index):
            app_name = app_names[index % len(app_names)]
            worker = workers[index]
            worker.refresh()
            result = worker.query(
                f"{app_name} only source", method="vector", context=contexts[app_name]
            )
            return app_name, result["sources"]

        with ThreadPoolExecutor(max_workers=6) as pool:
            refreshed_results = list(pool.map(refresh_and_query, range(6)))
        for app_name, sources in refreshed_results:
            assert sources
            assert all(item["text"] in allowed_texts[app_name] for item in sources)
        activity = {"id": "cross-worker", "tenant_id": tenant, "application_id": "app-a", "environment": "staging", "query": "persisted activity"}
        repository_a.append_activity("runs", activity)
        assert activity in repository_b.list_activity("runs")
    finally:
        for app_name in app_names:
            repository_a.delete_document((tenant, app_name, "staging", "same-id"))
            repository_a.delete_document((tenant, app_name, "staging", "committed-before-crash"))
            for index in range(4):
                repository_a.delete_document((tenant, app_name, "staging", f"concurrent-{index}"))
        repository_a.delete_document((tenant, "shared-namespace-app", "staging", "shared-namespace-doc"))
        with connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM workspace_activity WHERE tenant_id=%s", (tenant,))
                cursor.execute("DELETE FROM registered_applications WHERE ragguard_tenant_id=%s", (tenant,))
