from types import SimpleNamespace

import pytest

from ragguard.api import middleware
from fastapi.testclient import TestClient

from ragguard.auth.principal import TenantAuthorizationError, VerifiedPrincipal
from ragguard.auth.tenant_context import TenantContext
from ragguard.api.app import app
from ragguard.config import AuthenticationSettings, ServiceAuthSettings, Settings
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


def test_development_workspace_uses_ragguard_identity_by_default():
    from ragguard.config import load_settings

    settings = load_settings("configs/development.yaml")

    assert len(settings.tenant_policies) == 1
    assert settings.tenant_policies[0].tenant_id == "development"
    assert settings.tenant_policies[0].application_id == "ragguard"


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
    from ragguard.api import runtime
    from ragguard.auth.repository import InMemoryAuthRepository
    from ragguard.observability.application_repository import InMemoryApplicationRepository
    from ragguard.tenants.application_registration import ApplicationRegistration
    repository = InMemoryAuthRepository()
    repository.grant_membership(
        "https://identity.example.test/", "user-123", "tenant-a", ("viewer",)
    )
    repository.grant_application_membership(
        "https://identity.example.test/", "user-123", "tenant-a",
        "app-a", "production", ("admin",),
    )
    monkeypatch.setattr(runtime, "auth_repository", repository)
    applications = InMemoryApplicationRepository()
    applications.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a", application_id="app-a", display_name="App A",
        environment="production", knowledge_source="observation_only",
    ))
    applications.upsert(ApplicationRegistration(
        ragguard_tenant_id="tenant-a", application_id="app-b", display_name="App B",
        environment="production", knowledge_source="observation_only",
    ))
    monkeypatch.setattr(runtime, "application_repository", applications)
    settings = Settings(
        environment="production",
        authentication=AuthenticationSettings(
            mode="oidc",
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
    assert allowed.application_id == "app-a"

    with pytest.raises(PermissionError, match="No authorized application"):
        middleware.resolve_request_context(SimpleNamespace(headers={
            "X-RAGGuard-Tenant": "tenant-a",
            "X-RAGGuard-Application": "app-b",
            "X-RAGGuard-Environment": "production",
        }))

    with pytest.raises(TenantAuthorizationError):
        middleware.resolve_request_context(SimpleNamespace(
            headers={
                "X-RAGGuard-Tenant": "tenant-b",
                "X-RAGGuard-User": "another-user",
                "X-RAGGuard-Roles": "admin",
            },
        ))


def test_application_admin_can_use_app_scope_but_cannot_repair(monkeypatch):
    from dataclasses import replace
    from ragguard.api import app as app_module

    context = replace(
        TenantContext(
            tenant_id="tenant-a", application_id="app-a", environment="production",
            user_id="admin-user", roles=("viewer",), vector_namespace="tenant-a",
            policy_version="v1", index_version="v1",
        ),
        application_memberships=(("app-a", "production", ("admin",)),),
    )
    settings = Settings(
        environment="production",
        authentication=AuthenticationSettings(mode="oidc"),
    )
    monkeypatch.setattr(app_module, "load_settings", lambda: settings)
    monkeypatch.setattr(app_module, "resolve_request_context", lambda request: context)
    client = TestClient(app)

    query = client.post("/api/v1/query", json={})
    repair = client.post("/api/v1/repair", json={})

    assert query.status_code == 422
    assert repair.status_code == 403
    assert "RAGGuard tenant operator" in repair.json()["detail"]
