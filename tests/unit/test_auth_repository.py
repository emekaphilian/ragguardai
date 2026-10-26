from datetime import datetime, timedelta, timezone

from ragguard.auth.repository import InMemoryAuthRepository


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
