import json
from datetime import datetime, timezone

from ragguard.observability.observation_activity import ObservationRecord
from ragguard.observability.observation_repository import InMemoryObservationRepository
from ragguard.persistence.observation_repository import (
    PostgreSQLObservationRepository,
    create_observation_repository,
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
        if query.lstrip().startswith("INSERT INTO observations"):
            self.connection.row = tuple(
                json.loads(value) if index >= 6 else value
                for index, value in enumerate(parameters)
            )
        elif query.lstrip().startswith("SELECT COUNT(*) FROM observations"):
            self.connection.fetchone_result = (1 if self.connection.row else 0,)
        elif "WHERE observation_id = %s" in query:
            row = self.connection.row
            self.connection.fetchone_result = (
                row if row and row[0] == parameters[0] else None
            )
        elif query.lstrip().startswith("SELECT observation_id,"):
            self.connection.fetchall_result = (
                [self.connection.row] if self.connection.row else []
            )

    def fetchone(self):
        return self.connection.fetchone_result

    def fetchall(self):
        return self.connection.fetchall_result


class FakeConnection:
    def __init__(self):
        self.queries = []
        self.row = None
        self.fetchone_result = None
        self.fetchall_result = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return FakeCursor(self)


def make_record():
    return ObservationRecord(
        observation_id="observation-1",
        ragguard_tenant_id="internal-a",
        application_id="trustassist",
        created_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        status="healthy",
        query="refund policy",
        evaluation={"status": "HEALTHY", "retrieved_count": 5},
        observation={"contract_version": "v1", "query": "refund policy"},
        failure=None,
        recovery=None,
    )


def test_postgres_observation_repository_round_trips_and_filters():
    connection = FakeConnection()
    repository = PostgreSQLObservationRepository(
        connection_factory=lambda: connection,
    )
    record = make_record()

    repository.save(record)
    assert repository.get(record.observation_id) == record
    assert repository.list(
        ragguard_tenant_id="internal-a",
        application_id="trustassist",
        status="healthy",
        failure_detected=False,
        limit=25,
        offset=50,
    ) == [record]
    assert repository.count(ragguard_tenant_id="internal-a") == 1

    query, parameters = connection.queries[-2]
    assert "ragguard_tenant_id = %s" in query
    assert "application_id = %s" in query
    assert "status = %s" in query
    assert "failure IS NULL" in query
    assert parameters == (
        "internal-a", "trustassist", "healthy", 25, 50,
    )


def test_observation_repository_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("RAGGUARD_AUDIT_BACKEND", raising=False)
    assert isinstance(create_observation_repository(), InMemoryObservationRepository)
