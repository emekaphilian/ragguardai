from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

KnowledgeSource = Literal["managed_index", "external_rag_api", "observation_only"]


@dataclass(frozen=True, slots=True)
class ApplicationRegistration:
    ragguard_tenant_id: str
    application_id: str
    display_name: str
    environment: str
    knowledge_source: KnowledgeSource
    repair_authorized: bool = False
    context_verification_authorized: bool = False
    independent_verification_authorized: bool = False
    vector_namespace: str | None = None
    query_endpoint_url: str | None = None
    query_token_env_var: str | None = None
    repair_endpoint_url: str | None = None
    repair_token_env_var: str | None = None
    observation_token_env_var: str | None = None
    observation_token_hash: str | None = None
    active: bool = True

    @property
    def queryable(self) -> bool:
        if self.knowledge_source == "managed_index":
            return bool(self.vector_namespace)
        return self.knowledge_source == "external_rag_api" and bool(
            self.query_endpoint_url
        )

    def public_dict(self) -> dict[str, str | bool | None]:
        return {
            "application_id": self.application_id,
            "display_name": self.display_name,
            "environment": self.environment,
            "knowledge_source": self.knowledge_source,
            "active": self.active,
            "queryable": self.queryable,
            "observation_enabled": bool(
                self.observation_token_env_var or self.observation_token_hash
            ),
            "context_verification_authorized": self.context_verification_authorized,
            "independent_verification_authorized": self.independent_verification_authorized,
            "repair_authorized": self.repair_authorized,
        }
