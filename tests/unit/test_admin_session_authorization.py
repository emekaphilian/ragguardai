from datetime import datetime, timedelta, timezone
import hashlib

import pytest
from fastapi import HTTPException, Request

from ragguard.api.routes import admin
from ragguard.auth.repository import InMemoryAuthRepository
from ragguard.config import AuthenticationSettings, ServiceAuthSettings, Settings


def make_request(session_id="session", csrf="csrf"):
    headers = [(b"cookie", f"ragguard_session={session_id}".encode())]
    if csrf:
        headers.append((b"x-csrf-token", csrf.encode()))
    return Request({"type": "http", "method": "POST", "path": "/api/v1/admin/applications/onboard", "headers": headers})


def setup_admin(monkeypatch, roles=("admin",)):
    repository = InMemoryAuthRepository()
    repository.save_session("session", {
        "issuer": "https://identity.example",
        "subject": "admin-user",
        "csrf_hash": hashlib.sha256(b"csrf").hexdigest(),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
    })
    repository.grant_membership("https://identity.example", "admin-user", "tenant-a", roles)
    monkeypatch.setattr(admin, "auth_repository", repository)
    monkeypatch.setattr(admin, "load_settings", lambda: Settings(
        environment="production",
        service_auth=ServiceAuthSettings(tenant_id="tenant-a"),
        authentication=AuthenticationSettings(mode="oidc", oidc_issuer="https://identity.example"),
    ))
    monkeypatch.delenv("RAGGUARD_ADMIN_TOKEN", raising=False)
    return repository


def test_oidc_session_admin_is_authorized_from_server_membership(monkeypatch):
    setup_admin(monkeypatch)
    admin._require_admin(None, make_request(), "tenant-a")


def test_non_admin_tenant_member_cannot_use_administrative_session(monkeypatch):
    setup_admin(monkeypatch, roles=("operator",))
    with pytest.raises(HTTPException) as exc:
        admin._require_admin(None, make_request(), "tenant-a")
    assert exc.value.status_code == 403


def test_admin_session_requires_valid_csrf_and_selected_tenant_membership(monkeypatch):
    setup_admin(monkeypatch)
    with pytest.raises(HTTPException) as csrf_error:
        admin._require_admin(None, make_request(csrf="forged"), "tenant-a")
    assert csrf_error.value.status_code == 403

    with pytest.raises(HTTPException) as tenant_error:
        admin._require_admin(None, make_request(), "tenant-b")
    assert tenant_error.value.status_code == 403


def test_application_admin_is_limited_to_its_application(monkeypatch):
    repository = setup_admin(monkeypatch, roles=("viewer",))
    repository.grant_application_membership(
        "https://identity.example", "admin-user", "tenant-a",
        "trustassist", "production", ("admin",),
    )

    admin._require_application_admin(
        None, make_request(), "tenant-a", "trustassist", "production"
    )
    with pytest.raises(HTTPException) as exc:
        admin._require_application_admin(
            None, make_request(), "tenant-a", "biomedicalrag", "production"
        )
    assert exc.value.status_code == 403
