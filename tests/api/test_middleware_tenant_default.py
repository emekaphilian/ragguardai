from types import SimpleNamespace

from ragguard.api import middleware
from ragguard.config import ServiceAuthSettings, Settings
from ragguard.tenants.models import TenantPolicy


def test_request_without_tenant_header_uses_service_observation_tenant(monkeypatch):
    settings = Settings(
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
