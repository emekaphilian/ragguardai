from types import SimpleNamespace

import pytest

from ragguard.api import middleware
from fastapi.testclient import TestClient

from ragguard.auth.principal import TenantAuthorizationError, VerifiedPrincipal
from ragguard.api.app import app
from ragguard.config import AuthenticationSettings, ServiceAuthSettings, Settings, TenantMembership
from ragguard.tenants.models import TenantPolicy


def test_request_without_tenant_header_uses_service_observation_tenant(monkeypatch):
    settings = Settings(
        authentication=AuthenticationSettings(mode="development_headers"),
        tenant_policies=(
            TenantPolicy(
                tenant_id="internal-production",
                application_id="trustassist",
                environment="production",
                vector_namespace="internal-production",
            ),
        ),
        service_auth=ServiceAuthSettings(
            token="service-token",
            application="trustassist",
            tenant_id="internal-production",
        ),
    )
    monkeypatch.setattr(middleware, "load_settings", lambda: settings)

    context = middleware.resolve_request_context(SimpleNamespace(headers={}))

    assert context.tenant_id == "internal-production"
    assert context.application_id == "trustassist"


def test_explicit_tenant_header_still_overrides_service_default(monkeypatch):
    settings = Settings(
        authentication=AuthenticationSettings(mode="development_headers"),
        tenant_policies=(
            TenantPolicy(
                tenant_id="internal-production",
                application_id="trustassist",
                environment="production",
                vector_namespace="internal-production",
            ),
            TenantPolicy(
                tenant_id="workspace-a",
                application_id="app-a",
                environment="development",
                vector_namespace="workspace-a",
            ),
        ),
        service_auth=ServiceAuthSettings(
            token="service-token",
            application="trustassist",
            tenant_id="internal-production",
        ),
    )
    monkeypatch.setattr(middleware, "load_settings", lambda: settings)

    context = middleware.resolve_request_context(SimpleNamespace(
        headers={"X-RAGGuard-Tenant": "workspace-a"},
    ))

    assert context.tenant_id == "workspace-a"
    assert context.application_id == "app-a"


def test_production_rejects_development_header_authentication():
    try:
        Settings(
            environment="production",
            authentication=AuthenticationSettings(mode="development_headers"),
        )
    except ValueError as exc:
        assert "restricted to development and tests" in str(exc)
    else:
        raise AssertionError("production must reject development-header authentication")


def test_unconfigured_authentication_does_not_trust_spoofed_identity_headers(monkeypatch):
    settings = Settings(
        environment="production",
        authentication=AuthenticationSettings(mode="disabled"),
        tenant_policies=(TenantPolicy(
            tenant_id="tenant-a",
            application_id="app-a",
            environment="production",
            vector_namespace="tenant-a",
        ),),
    )
    monkeypatch.setattr(middleware, "load_settings", lambda: settings)
    response = TestClient(app).get(
        "/api/v1/dashboard",
        headers={
            "X-RAGGuard-Tenant": "tenant-a",
            "X-RAGGuard-User": "admin",
            "X-RAGGuard-Roles": "admin",
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Human-user authentication is not configured."}


def test_health_check_remains_available_without_dashboard_auth(monkeypatch):
    settings = Settings(
        environment="production",
        authentication=AuthenticationSettings(mode="disabled"),
    )
    monkeypatch.setattr(middleware, "load_settings", lambda: settings)

    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200


def test_changing_tenant_selection_does_not_bypass_server_membership(monkeypatch):
    settings = Settings(
        environment="production",
        authentication=AuthenticationSettings(
            mode="oidc",
            tenant_memberships=(TenantMembership(
                issuer="https://identity.example.test/",
                subject="user-123",
                tenant_id="tenant-a",
                roles=("viewer",),
            ),),
        ),
        tenant_policies=(
            TenantPolicy(
                tenant_id="tenant-a",
                application_id="app-a",
                environment="production",
                vector_namespace="tenant-a",
            ),
            TenantPolicy(
                tenant_id="tenant-b",
                application_id="app-b",
                environment="production",
                vector_namespace="tenant-b",
            ),
        ),
    )
    monkeypatch.setattr(middleware, "load_settings", lambda: settings)
    monkeypatch.setattr(
        middleware,
        "authenticate_principal",
        lambda request, settings: VerifiedPrincipal(
            issuer="https://identity.example.test/",
            subject="user-123",
            roles=("admin",),
            authentication_method="oidc",
        ),
    )

    allowed = middleware.resolve_request_context(SimpleNamespace(
        headers={"X-RAGGuard-Tenant": "tenant-a"},
    ))
    assert allowed.tenant_id == "tenant-a"
    assert allowed.roles == ("viewer",)

    with pytest.raises(TenantAuthorizationError):
        middleware.resolve_request_context(SimpleNamespace(
            headers={
                "X-RAGGuard-Tenant": "tenant-b",
                "X-RAGGuard-User": "another-user",
                "X-RAGGuard-Roles": "admin",
            },
        ))
