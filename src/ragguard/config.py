from dataclasses import dataclass
from pathlib import Path
import os
import yaml


@dataclass(frozen=True)
class Thresholds:
    context_precision: float = 0.70
    context_recall: float = 0.70
    faithfulness: float = 0.70
    answer_relevancy: float = 0.70


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool = False
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    fallback_providers: tuple[str, ...] = ()
    timeout: float = 15.0
    api_key: str | None = None


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    top_k: int = 5
    thresholds: Thresholds = Thresholds()
    llm: LLMSettings = LLMSettings()
    tenant_policies: tuple = ()


def _resolve_llm_settings(data: dict | None) -> LLMSettings:
    llm_data = (data or {}).get("llm", {})
    env_provider = os.getenv("RAGGUARD_LLM_PROVIDER", llm_data.get("provider", "openai"))
    env_model = os.getenv("RAGGUARD_LLM_MODEL", llm_data.get("model", "gpt-4o-mini"))
    fallback_value = os.getenv("RAGGUARD_LLM_FALLBACK_PROVIDERS")
    if fallback_value is None:
        fallback_value = llm_data.get("fallback_providers", "")
    if isinstance(fallback_value, str):
        fallback_providers = tuple(item.strip().lower() for item in fallback_value.split(",") if item.strip())
    else:
        fallback_providers = tuple(str(item).strip().lower() for item in fallback_value)
    env_enabled_value = os.getenv("RAGGUARD_LLM_ENABLED", str(llm_data.get("enabled", False))).strip().lower()
    enabled = env_enabled_value in {"1", "true", "yes", "on"}
    if llm_data.get("enabled") is not None:
        enabled = bool(llm_data["enabled"]) or enabled
    return LLMSettings(
        enabled=enabled,
        provider=env_provider,
        model=env_model,
        fallback_providers=fallback_providers,
        timeout=float(llm_data.get("timeout", float(os.getenv("RAGGUARD_LLM_TIMEOUT", "15.0")))),
        api_key=os.getenv("OPENAI_API_KEY") or llm_data.get("api_key"),
    )


def load_settings(path: str | None = None) -> Settings:
    path = path or os.getenv("RAGGUARD_CONFIG", "configs/development.yaml")
    p = Path(path)
    if not p.exists():
        return Settings(llm=_resolve_llm_settings({}))
    data = yaml.safe_load(p.read_text()) or {}
    base_llm = _resolve_llm_settings(data)
    from ragguard.tenants.models import TenantPolicy
    policies = []
    for tenant_id, tenant_data in (data.get("tenants", {}) or {}).items():
        tenant_data = tenant_data or {}
        policy_data = tenant_data.get("policy", {}) or {}
        policies.append(TenantPolicy(
            tenant_id=tenant_id,
            application_id=tenant_data.get("application_id", tenant_id),
            environment=data.get("environment", "development"),
            vector_namespace=tenant_data.get("vector_namespace", tenant_id),
            policy_version=policy_data.get("version", "v1"),
            index_version=tenant_data.get("index_version", "v1"),
            llm=_resolve_llm_settings({"llm": tenant_data.get("llm", {})}),
        ))
    return Settings(
        environment=data.get("environment", "development"),
        top_k=int(data.get("top_k", 5)),
        thresholds=Thresholds(**data.get("thresholds", {})),
        llm=base_llm,
        tenant_policies=tuple(policies),
    )
