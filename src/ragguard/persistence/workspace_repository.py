"""Durable managed-document and workspace-activity repositories."""
from __future__ import annotations

import json
import os
from threading import RLock
from typing import Any

from ragguard.common.schemas import Document

from .database import connect, selected_persistence_backend


class WorkspaceRepository:
    def list_documents(self, *, include_recycled: bool = False) -> list[tuple[Document, bool, str | None]]:
        raise NotImplementedError

    def save_document(self, document: Document, *, recycled: bool = False, source_relative_path: str | None = None) -> None:
        raise NotImplementedError

    def save_documents(self, documents: list[Document]) -> None:
        raise NotImplementedError

    def delete_document(self, identity: tuple[str, str, str, str]) -> bool:
        raise NotImplementedError

    def append_activity(self, kind: str, value: dict[str, Any]) -> None:
        raise NotImplementedError

    def list_activity(self, kind: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def clear_activity(self, kind: str | None = None) -> dict[str, int]:
        raise NotImplementedError


class InMemoryWorkspaceRepository(WorkspaceRepository):
    def __init__(self):
        self.documents: dict[tuple[str, str, str, str], tuple[Document, bool, str | None]] = {}
        self.activity: dict[str, list[dict[str, Any]]] = {"runs": [], "failures": [], "repairs": []}
        self.lock = RLock()

    def list_documents(self, *, include_recycled=False):
        with self.lock:
            return [row for row in self.documents.values() if include_recycled or not row[1]]

    def save_document(self, document, *, recycled=False, source_relative_path=None):
        md = document.metadata
        key = (str(md.get("ragguard_tenant_id", "development")), str(md.get("application_id", "development")), str(md.get("environment", "development")), document.document_id)
        with self.lock:
            self.documents[key] = (document, recycled, source_relative_path)

    def save_documents(self, documents):
        rows = []
        for document in documents:
            md = document.metadata
            key = (str(md.get("ragguard_tenant_id", "development")), str(md.get("application_id", "development")), str(md.get("environment", "development")), document.document_id)
            rows.append((key, (document, False, None)))
        with self.lock:
            self.documents.update(rows)

    def delete_document(self, identity):
        with self.lock:
            return self.documents.pop(identity, None) is not None

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


class PostgreSQLWorkspaceRepository(WorkspaceRepository):
    def __init__(self, database_url: str | None = None, *, connection_factory=None):
        self.database_url = database_url
        self.connection_factory = connection_factory

    def _connect(self):
        return self.connection_factory() if self.connection_factory else connect(self.database_url)

    def list_documents(self, *, include_recycled=False):
        sql = "SELECT document, recycled, source_relative_path, ragguard_tenant_id, application_id, environment, namespace FROM managed_documents"
        if not include_recycled:
            sql += " WHERE NOT recycled"
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
        documents = []
        for document_json, recycled, source_path, tenant_id, application_id, environment, namespace in rows:
            document = Document.model_validate(document_json)
            document.metadata = {
                **document.metadata,
                "ragguard_tenant_id": tenant_id,
                "application_id": application_id,
                "environment": environment,
                "tenant_namespace": namespace,
                "identity_scope_explicit": True,
            }
            documents.append((document, recycled, source_path))
        return documents

    def save_document(self, document, *, recycled=False, source_relative_path=None):
        self._save_documents([(document, recycled, source_relative_path)])

    def save_documents(self, documents):
        self._save_documents([(document, False, None) for document in documents])

    def _save_documents(self, entries):
        if not entries:
            return
        parameters = []
        for document, recycled, source_relative_path in entries:
            md = document.metadata
            parameters.append((md.get("ragguard_tenant_id", "development"), md.get("application_id", "development"), md.get("environment", "development"), document.document_id, md.get("tenant_namespace", "development"), json.dumps(document.model_dump(mode="json")), recycled, source_relative_path))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                query = """INSERT INTO managed_documents
                    (ragguard_tenant_id, application_id, environment, document_id, namespace, document, recycled, source_relative_path)
                    VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                    ON CONFLICT (ragguard_tenant_id, application_id, environment, document_id)
                    DO UPDATE SET namespace=EXCLUDED.namespace, document=EXCLUDED.document,
                    recycled=EXCLUDED.recycled, source_relative_path=EXCLUDED.source_relative_path,
                    updated_at=now()"""
                cursor.executemany(query, parameters)

    def delete_document(self, identity):
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM managed_documents WHERE ragguard_tenant_id=%s AND application_id=%s AND environment=%s AND document_id=%s", identity)
                return cursor.rowcount > 0

    def append_activity(self, kind, value):
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO workspace_activity (kind, tenant_id, application_id, environment, payload) VALUES (%s,%s,%s,%s,%s::jsonb)", (kind, value.get("tenant_id", "development"), value.get("application_id", "development"), value.get("environment", "development"), json.dumps(value)))

    def list_activity(self, kind):
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT payload FROM workspace_activity WHERE kind=%s ORDER BY created_at DESC", (kind,))
                rows = cursor.fetchall()
        return [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in rows]

    def clear_activity(self, kind=None):
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT kind, count(*) FROM workspace_activity" + (" WHERE kind=%s" if kind else "") + " GROUP BY kind", (kind,) if kind else ())
                counts = {kind: int(count) for kind, count in cursor.fetchall()}
                cursor.execute("DELETE FROM workspace_activity" + (" WHERE kind=%s" if kind else ""), (kind,) if kind else ())
        return {kind: counts.get(kind, 0) for kind in ("runs", "failures", "repairs")}


def create_workspace_repository(*, backend: str | None = None, database_url: str | None = None):
    backend = selected_persistence_backend(backend)
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryWorkspaceRepository()
    if backend in {"postgres", "postgresql"}:
        if not database_url and not os.getenv("RAGGUARD_DATABASE_URL"):
            raise ValueError("RAGGUARD_DATABASE_URL is required for PostgreSQL workspace storage.")
        return PostgreSQLWorkspaceRepository(database_url)
    raise ValueError(f"Unsupported workspace backend: {backend}")
