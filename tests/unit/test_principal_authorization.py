from types import SimpleNamespace

import pytest

from ragguard.auth.authorization import resolve_authorized_tenant
from ragguard.auth.principal import (
    AuthenticationUnavailable,
    TenantAuthorizationError,
    VerifiedPrincipal,
)
from ragguard.config import AuthenticationSettings, Settings
from ragguard.tenants.models import TenantPolicy


def settings_with_memberships():
    return Settings(
        environment="production",
        authentication=AuthenticationSettings(
            mode="oidc",
        ),
        tenant_policies=(
            TenantPolicy(
                tenant_id="tenant-a",
                application_id="app-a",
                environment="production",
                vector_namespace="tenant-a-index",
            ),
            TenantPolicy(
                tenant_id="tenant-b",
                application_id="app-b",
                environment="production",
                vector_namespace="tenant-b-index",
            ),
        ),
    )


def test_membership_uses_issuer_subject_and_tenant_and_roles_from_server_policy(monkeypatch):
    settings = settings_with_memberships()
    from ragguard.api import runtime
    from ragguard.auth.repository import InMemoryAuthRepository
    repository = InMemoryAuthRepository()
    repository.grant_membership("https://identity.example.test/", "user-123", "tenant-a", ("reader",))
    monkeypatch.setattr(runtime, "auth_repository", repository)
    principal = VerifiedPrincipal(
        issuer="https://identity.example.test/",
        subject="user-123",
        roles=("admin",),  # provider roles do not override RAGGuard policy
        authentication_method="oidc",
    )

    context = resolve_authorized_tenant(principal, "tenant-a", settings)

    assert context.tenant_id == "tenant-a"
    assert context.application_id == "app-a"
    assert context.user_id == "user-123"
    assert context.roles == ("reader",)


@pytest.mark.parametrize(
    ("issuer", "subject", "tenant_id"),
    [
        ("https://untrusted.example/", "user-123", "tenant-a"),
        ("https://identity.example.test/", "other-user", "tenant-a"),
        ("https://identity.example.test/", "user-123", "tenant-b"),
    ],
)
def test_membership_rejects_wrong_issuer_subject_or_tenant(issuer, subject, tenant_id, monkeypatch):
    from ragguard.api import runtime
    from ragguard.auth.repository import InMemoryAuthRepository
    repository = InMemoryAuthRepository()
    repository.grant_membership("https://identity.example.test/", "user-123", "tenant-a", ("reader",))
    monkeypatch.setattr(runtime, "auth_repository", repository)
    with pytest.raises(TenantAuthorizationError):
        resolve_authorized_tenant(
            VerifiedPrincipal(issuer=issuer, subject=subject, authentication_method="oidc"),
            tenant_id,
            settings_with_memberships(),
        )


def test_development_headers_cannot_be_used_outside_development():
    from ragguard.auth.providers import DevelopmentHeaderAuthenticator

    settings = Settings(
        environment="testing",
        authentication=AuthenticationSettings(mode="development_headers"),
    )
    principal = DevelopmentHeaderAuthenticator().authenticate(
        SimpleNamespace(headers={"X-RAGGuard-User": "test-user"}),
        settings,
    )
    assert principal.issuer == "urn:ragguard:development"
    assert principal.subject == "test-user"

    production_settings = Settings(
        environment="production",
        authentication=AuthenticationSettings(mode="oidc"),
    )
    with pytest.raises(AuthenticationUnavailable, match="Development-header authentication is disabled"):
        DevelopmentHeaderAuthenticator().authenticate(
            SimpleNamespace(headers={"X-RAGGuard-User": "attacker"}),
            production_settings,
        )
