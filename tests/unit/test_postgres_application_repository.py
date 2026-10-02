from ragguard.tenants.models import TenantPolicy
from ragguard.tenants.application_registration import ApplicationRegistration
from ragguard.persistence.application_repository import PostgreSQLApplicationRepository


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.fetchone_result = None
        self.fetchall_result = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, parameters):
        self.connection.queries.append((query, parameters))
        if query.lstrip().startswith("INSERT INTO registered_applications"):
            if "RETURNING application_id" in query:
                key = (parameters[0], parameters[1], parameters[3])
                if key in self.connection.rows:
                    self.fetchone_result = None
                else:
                    self.connection.rows[key] = (
                        parameters[0], parameters[1], parameters[1], parameters[3],
                        "managed_index", parameters[4], None, None, None, True, False,
                    )
                    self.fetchone_result = (parameters[1],)
            else:
                row = tuple(parameters)
                key = (row[0], row[1], row[3])
                self.connection.rows[key] = row
        elif query.lstrip().startswith("SELECT"):
            tenant_id = parameters[0]
            if "application_id = %s" in query:
                application_id = parameters[1]
                environment = parameters[2]
                row = self.connection.rows.get((tenant_id, application_id, environment))
                self.fetchone_result = row if row and ("AND active" not in query or row[9]) else None
            else:
                self.fetchall_result = [
                    row for key, row in self.connection.rows.items()
                    if key[0] == tenant_id and ("AND active" not in query or row[9])
                ]

    def fetchone(self):
        return self.fetchone_result

    def fetchall(self):
        return self.fetchall_result


class FakeConnection:
    def __init__(self):
        self.rows = {}
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return FakeCursor(self)


def test_postgres_application_repository_upsert_scope_and_bootstrap():
    connection = FakeConnection()
    repository = PostgreSQLApplicationRepository(
        connection_factory=lambda: connection,
    )
    application = ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="supportbot",
        display_name="Support Bot",
        environment="production",
        knowledge_source="external_rag_api",
        query_endpoint_url="https://support.example.test/query",
        query_token_env_var="SUPPORTBOT_QUERY_TOKEN",
        observation_token_env_var="SUPPORTBOT_OBSERVATION_TOKEN",
        repair_authorized=True,
    )

    repository.upsert(application)

    assert repository.get("tenant-a", "supportbot", "production") == application
    assert application.repair_authorized is True
    assert repository.get("tenant-a", "supportbot", "production").vector_namespace is None
    assert repository.list("tenant-a") == [application]
    assert repository.list("tenant-b") == []
    assert "SUPPORTBOT_QUERY_TOKEN" in connection.queries[0][1]
    assert "actual-token" not in str(connection.queries)
    assert ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="unapproved",
        display_name="Unapproved",
        environment="production",
        knowledge_source="observation_only",
    ).repair_authorized is False

    policies = (
        TenantPolicy(
            tenant_id="tenant-a",
            application_id="managed-app",
            environment="production",
            vector_namespace="managed-prod",
        ),
    )
    assert repository.bootstrap(policies) == 1
    assert repository.bootstrap(policies) == 0
    managed = repository.get("tenant-a", "managed-app", "production")
    assert managed is not None
    assert managed.knowledge_source == "managed_index"
    assert managed.vector_namespace == "managed-prod"
