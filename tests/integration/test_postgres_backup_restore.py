"""End-to-end pg_dump/pg_restore round-trip, enabled in the PostgreSQL CI job."""
import os
import shutil
import subprocess
from urllib.parse import unquote, urlparse
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from ragguard.api.runtime import Workspace
from ragguard.auth.tenant_context import TenantContext
from ragguard.common.schemas import Document
from ragguard.persistence.database import apply_migrations
from ragguard.persistence.workspace_repository import PostgreSQLWorkspaceRepository
from ragguard.persistence.application_repository import PostgreSQLApplicationRepository
from ragguard.tenants.application_registration import ApplicationRegistration


DATABASE_URL = os.getenv("RAGGUARD_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not shutil.which("pg_dump") or not shutil.which("pg_restore"),
    reason="PostgreSQL URL and pg_dump/pg_restore are required",
)


def _pg_env(database_url):
    parsed = urlparse(database_url)
    env = os.environ.copy()
    env.update({
        "PGHOST": parsed.hostname or "localhost",
        "PGPORT": str(parsed.port or 5432),
        "PGUSER": unquote(parsed.username or ""),
        "PGPASSWORD": unquote(parsed.password or ""),
        "PGDATABASE": parsed.path.lstrip("/"),
    })
    sslmode = dict(pair.split("=", 1) for pair in parsed.query.split("&") if "=" in pair).get("sslmode")
    if sslmode:
        env["PGSSLMODE"] = sslmode
    return env


def test_workspace_database_backup_restores_documents_and_activity(tmp_path):
    apply_migrations(database_url=DATABASE_URL)
    tenant = f"backup-test-{uuid4().hex}"
    context = TenantContext(tenant, "app", "test", None, (), f"{tenant}-ns", "v1", "v1")
    repository = PostgreSQLWorkspaceRepository(DATABASE_URL)
    applications = PostgreSQLApplicationRepository(DATABASE_URL)
    workspace = Workspace(tmp_path / "raw", tmp_path / "recycle", repository=repository)
    restore_database = f"ragguard_restore_{uuid4().hex[:12]}"
    backup_file = tmp_path / "ragguard.dump"
    env = _pg_env(DATABASE_URL)
    try:
        workspace.ingest_documents([Document(document_id="durable-doc", text="backup restoration marker")], context)
        applications.upsert(ApplicationRegistration(
            ragguard_tenant_id=tenant, application_id="app", display_name="app",
            environment="test", knowledge_source="managed_index", vector_namespace=context.vector_namespace,
        ))
        repository.append_activity("runs", {
            "id": "durable-run", "tenant_id": tenant, "application_id": "app",
            "environment": "test", "query": "backup restoration marker",
        })
        subprocess.run(["pg_dump", "--format=custom", "--file", str(backup_file)], env=env, check=True, capture_output=True, text=True)
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restore_database)))
        subprocess.run(["pg_restore", "--no-owner", "--no-privileges", "--dbname", restore_database, str(backup_file)], env=env, check=True, capture_output=True, text=True)
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        restored_parameters = conninfo_to_dict(DATABASE_URL)
        restored_parameters["dbname"] = restore_database
        restored_url = make_conninfo(**restored_parameters)
        restored_repository = PostgreSQLWorkspaceRepository(restored_url)
        restored_workspace = Workspace(tmp_path / "restore-raw", tmp_path / "restore-recycle", repository=restored_repository)
        restored_workspace.refresh()
        assert [row["id"] for row in restored_workspace.document_rows(context)] == ["durable-doc"]
        assert any(row["id"] == "durable-run" for row in restored_repository.list_activity("runs"))
        assert PostgreSQLApplicationRepository(restored_url).get(tenant, "app", "test") is not None
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(restore_database))
            )
            connection.execute("DELETE FROM managed_documents WHERE ragguard_tenant_id=%s", (tenant,))
            connection.execute("DELETE FROM workspace_activity WHERE tenant_id=%s", (tenant,))
            connection.execute("DELETE FROM registered_applications WHERE ragguard_tenant_id=%s", (tenant,))
