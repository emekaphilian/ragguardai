"""Tenant identity propagated through every RAGGuard operation."""
from __future__ import annotations

from dataclasses import dataclass


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
