"""Opt-in persistence checks against an isolated PostgreSQL test database.

Set RAGGUARD_TEST_DATABASE_URL to run these restart and multi-instance checks.
Never point it at a production or shared staging database: the test cleans up
its uniquely named tenant rows after each case.
"""
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
        for _, app_name, sources in query_results:
            assert all(app_name in item["text"] for item in sources)
        for app_name, index in tasks:
            final_result = second.query(
                f"{app_name} concurrent marker {index}", method="vector", context=contexts[app_name]
            )
            assert final_result["sources"] and all(app_name in item["text"] for item in final_result["sources"])
        activity = {"id": "cross-worker", "tenant_id": tenant, "application_id": "app-a", "environment": "staging", "query": "persisted activity"}
        repository_a.append_activity("runs", activity)
        assert activity in repository_b.list_activity("runs")
    finally:
        for app_name in app_names:
            repository_a.delete_document((tenant, app_name, "staging", "same-id"))
            repository_a.delete_document((tenant, app_name, "staging", "committed-before-crash"))
            for index in range(4):
                repository_a.delete_document((tenant, app_name, "staging", f"concurrent-{index}"))
        with connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM workspace_activity WHERE tenant_id=%s", (tenant,))
                cursor.execute("DELETE FROM registered_applications WHERE ragguard_tenant_id=%s", (tenant,))
