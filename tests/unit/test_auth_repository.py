from datetime import datetime, timedelta, timezone

from ragguard.auth.repository import InMemoryAuthRepository, PostgreSQLAuthRepository


def test_session_store_hashes_cookie_identifier_and_expires_sessions():
    repository = InMemoryAuthRepository()
    session_id = "opaque-session-value"
    repository.save_session(session_id, {
        "issuer": "https://issuer.example",
        "subject": "user-1",
        "csrf_hash": "stored-csrf-digest",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
    })

    assert repository.get_session(session_id)["subject"] == "user-1"
    assert session_id not in repository._sessions

    repository.save_session("expired", {
        "issuer": "https://issuer.example",
        "subject": "user-2",
        "csrf_hash": "digest",
        "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
    })
    assert repository.get_session("expired") is None


def test_membership_grants_are_tenant_scoped_and_revocable():
    repository = InMemoryAuthRepository()
    repository.grant_membership("issuer", "user", "tenant-a", ("reader",))
    repository.grant_membership("issuer", "user", "tenant-b", ("operator",))

    assert repository.get_membership("issuer", "user", "tenant-a") == ("reader",)
    assert repository.get_membership("issuer", "user", "tenant-b") == ("operator",)
    assert repository.list_memberships("tenant-a") == [
        {"issuer": "issuer", "subject": "user", "tenant_id": "tenant-a", "roles": ["reader"]}
    ]

    repository.revoke_membership("issuer", "user", "tenant-a")
    assert repository.get_membership("issuer", "user", "tenant-a") is None
    assert repository.get_membership("issuer", "user", "tenant-b") == ("operator",)


def test_oidc_admin_bootstrap_is_one_time_and_does_not_restore_revoked_grant():
    repository = InMemoryAuthRepository()

    assert repository.bootstrap_admin_once("issuer", "admin", "tenant-a") is True
    assert repository.get_membership("issuer", "admin", "tenant-a") == ("admin",)

    repository.revoke_membership("issuer", "admin", "tenant-a")

    assert repository.bootstrap_admin_once("issuer", "admin", "tenant-a") is False
    assert repository.get_membership("issuer", "admin", "tenant-a") is None


def test_oidc_admin_bootstrap_preserves_existing_membership():
    repository = InMemoryAuthRepository()
    repository.grant_membership("issuer", "admin", "tenant-a", ("reader",))

    assert repository.bootstrap_admin_once("issuer", "admin", "tenant-a") is True
    assert repository.get_membership("issuer", "admin", "tenant-a") == ("reader",)


def test_postgres_admin_bootstrap_claims_persistent_one_time_marker():
    class FakeCursor:
        def __init__(self, database):
            self.database = database
            self.result = None

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, query, parameters=()):
            if "INSERT INTO auth_bootstrap_state" in query:
                if "oidc_admin" in self.database["bootstrap_state"]:
                    self.result = None
                else:
                    self.database["bootstrap_state"].add("oidc_admin")
                    self.result = ("oidc_admin",)
            elif "INSERT INTO tenant_memberships" in query:
                self.database["memberships"].setdefault(
                    tuple(parameters[:3]),
                    ("admin",),
                )
            elif "DELETE FROM tenant_memberships" in query:
                self.database["memberships"].pop(tuple(parameters), None)

        def fetchone(self):
            return self.result

    class FakeConnection:
        def __init__(self, database):
            self.database = database

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return FakeCursor(self.database)

    database = {"bootstrap_state": set(), "memberships": {}}
    repository = PostgreSQLAuthRepository(
        connection_factory=lambda: FakeConnection(database),
    )

    assert repository.bootstrap_admin_once("issuer", "admin", "tenant-a") is True
    assert database["memberships"][("issuer", "admin", "tenant-a")] == ("admin",)

    with FakeConnection(database) as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM tenant_memberships WHERE issuer=%s AND subject=%s AND tenant_id=%s",
            ("issuer", "admin", "tenant-a"),
        )

    assert repository.bootstrap_admin_once("issuer", "admin", "tenant-a") is False
    assert ("issuer", "admin", "tenant-a") not in database["memberships"]
