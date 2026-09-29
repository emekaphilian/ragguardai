import json
from contextlib import contextmanager

from ragguard.observability.recovery_audit import (
    RecoveryAuditRecord,
    RecoveryEventType,
)
from ragguard.observability.recovery_repository import InMemoryRecoveryAuditRepository
from ragguard.persistence.repositories import (
    PostgreSQLRecoveryAuditRepository,
    create_recovery_audit_repository,
)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, parameters):
        self.connection.queries.append((query, parameters))
        if query.lstrip().startswith("SELECT record FROM recovery_audits WHERE recovery_id"):
            self.connection.fetchone_result = (
                self.connection.document,
            ) if self.connection.document else None
        elif query.lstrip().startswith("SELECT COUNT(*) FROM recovery_audits"):
            self.connection.fetchone_result = self.connection.count_result
        elif query.lstrip().startswith("SELECT record FROM recovery_audits"):
            self.connection.fetchall_result = (
                [(self.connection.document,)] if self.connection.document else []
            )
        elif query.lstrip().startswith("DELETE FROM recovery_audits"):
            self.connection.fetchall_result = self.connection.deleted_rows
        elif query.lstrip().startswith("INSERT INTO recovery_audits"):
            self.connection.document = json.loads(parameters[-1])

    def fetchone(self):
        return self.connection.fetchone_result

    def fetchall(self):
        return self.connection.fetchall_result


class FakeConnection:
    def __init__(self):
        self.queries = []
        self.document = None
        self.fetchone_result = None
        self.fetchall_result = []
        self.count_result = (0,)
        self.deleted_rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return FakeCursor(self)


def test_postgres_repository_round_trips_audit_records():
    connection = FakeConnection()
    repository = PostgreSQLRecoveryAuditRepository(
        connection_factory=lambda: connection,
    )
    record = RecoveryAuditRecord.create(
        graph_run_id="graph-1",
        application_id="trustassist",
        tenant_id="customer-a",
        ragguard_tenant_id="internal-a",
        observation_snapshot={
            "contract_version": "v1",
            "query": "refund policy",
        },
    )
    record.add_event(RecoveryEventType.RUN_STARTED, status="started")

    repository.save(record)
    loaded = repository.get(record.recovery_id)
    listed = repository.list(
        ragguard_tenant_id="internal-a",
        tenant_id="customer-a",
        application_id="trustassist",
    )

    assert loaded is not None
    assert loaded.recovery_id == record.recovery_id
    assert loaded.events[0].event_type == RecoveryEventType.RUN_STARTED
    assert loaded.ragguard_tenant_id == "internal-a"
    assert loaded.observation_snapshot == {
        "contract_version": "v1",
        "query": "refund policy",
    }
    assert listed[0].tenant_id == "customer-a"
    assert "ragguard_tenant_id = %s" in connection.queries[-1][0]
    assert connection.queries[-1][1][-2:] == (100, 0)


def test_postgres_repository_uses_parameterized_filters():
    connection = FakeConnection()
    repository = PostgreSQLRecoveryAuditRepository(
        connection_factory=lambda: connection,
    )

    repository.list(
        ragguard_tenant_id="tenant-a",
        application_id="trustassist",
        limit=25,
    )

    query, parameters = connection.queries[-1]
    assert "ragguard_tenant_id = %s" in query
    assert "application_id = %s" in query
    assert parameters == ("tenant-a", "trustassist", 25, 0)


def test_postgres_repository_uses_offset_and_count():
    connection = FakeConnection()
    connection.count_result = (17,)
    repository = PostgreSQLRecoveryAuditRepository(
        connection_factory=lambda: connection,
    )

    repository.list(limit=25, offset=50)
    assert connection.queries[-1][1] == (25, 50)
    assert repository.count(ragguard_tenant_id="tenant-a") == 17
    assert "COUNT(*)" in connection.queries[-1][0]


def test_postgres_retention_only_deletes_completed_records():
    connection = FakeConnection()
    connection.deleted_rows = [("expired-1",), ("expired-2",)]
    repository = PostgreSQLRecoveryAuditRepository(
        connection_factory=lambda: connection,
    )

    from datetime import datetime, timezone

    deleted = repository.delete_expired(datetime(2026, 1, 1, tzinfo=timezone.utc))

    query, parameters = connection.queries[-1]
    assert deleted == 2
    assert "final_status <> 'running'" in query
    assert "completed_at" in query
    assert parameters[0].year == 2026


def test_audit_backend_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("RAGGUARD_AUDIT_BACKEND", raising=False)

    assert isinstance(create_recovery_audit_repository(), InMemoryRecoveryAuditRepository)


def test_postgres_backend_requires_database_url(monkeypatch):
    monkeypatch.delenv("RAGGUARD_DATABASE_URL", raising=False)

    try:
        create_recovery_audit_repository(backend="postgres")
    except ValueError as exc:
        assert "RAGGUARD_DATABASE_URL" in str(exc)
    else:
        raise AssertionError("PostgreSQL mode should require a database URL")


def test_postgres_backend_is_selected_without_connecting():
    repository = create_recovery_audit_repository(
        backend="postgres",
        database_url="postgresql://localhost/ragguard",
    )

    assert isinstance(repository, PostgreSQLRecoveryAuditRepository)


def test_postgres_backend_can_be_selected_from_environment(monkeypatch):
    monkeypatch.setenv("RAGGUARD_AUDIT_BACKEND", "postgres")
    monkeypatch.setenv(
        "RAGGUARD_DATABASE_URL",
        "postgresql://localhost/ragguard",
    )

    assert isinstance(
        create_recovery_audit_repository(),
        PostgreSQLRecoveryAuditRepository,
    )


@contextmanager
def migration_connection(captured):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql):
            captured.append(sql)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return Cursor()

    yield Connection()
