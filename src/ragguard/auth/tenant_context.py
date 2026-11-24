"""Tenant identity propagated through every RAGGuard operation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApplicationScope:
    tenant_id: str
    application_id: str
    environment: str
    vector_namespace: str

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "application_id",
            "environment",
            "vector_namespace",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")


@dataclass(frozen=True, slots=True)
class TenantContext:
    """The immutable security boundary for a request or background job.

    This object must be built from authenticated claims, never directly from
    untrusted request payloads. ``vector_namespace`` is deliberately explicit
    so storage adapters have a single, auditable isolation key.
    """

    tenant_id: str
    application_id: str
    environment: str
    user_id: str | None
    roles: tuple[str, ...]
    vector_namespace: str
    policy_version: str
    index_version: str
    # None means platform-wide tenant access (trusted service/dev context).
    # OIDC users receive explicit (application, environment, roles) grants.
    application_memberships: tuple[tuple[str, str, tuple[str, ...]], ...] | None = None

    def __post_init__(self) -> None:
        self.scope

    @property
    def scope(self) -> ApplicationScope:
        return ApplicationScope(
            tenant_id=self.tenant_id,
            application_id=self.application_id,
            environment=self.environment,
            vector_namespace=self.vector_namespace,
        )
