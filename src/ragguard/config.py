from dataclasses import dataclass, field
from pathlib import Path
import os
import math
from urllib.parse import urlparse
from urllib.parse import urlparse
import yaml

MAX_REPAIR_ATTEMPTS = 3
DEFAULT_AUDIT_RETENTION_DAYS = 90
DEFAULT_AUDIT_MAX_PAGE_SIZE = 100
DEFAULT_EVENT_RETENTION_DAYS = 30


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
class ServiceAuthSettings:
    token: str | None = None
    application: str = "ragguard"
    tenant_id: str = "development"


@dataclass(frozen=True)
class AuthenticationSettings:
    # ``disabled`` is the fail-closed default. Development headers require an
    # explicit mode in the local/test configuration.
    mode: str = "disabled"
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_token_auth_method: str = "client_secret_basic"
    oidc_redirect_uri: str | None = None
    frontend_url: str | None = None
    session_secret: str | None = None
    session_cookie_name: str = "ragguard_session"
    session_cookie_secure: bool = True
    session_cookie_samesite: str = "lax"
    session_ttl_seconds: int = 28800
    frontend_origins: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    top_k: int = 5
    thresholds: Thresholds = Thresholds()
    llm: LLMSettings = LLMSettings()
    tenant_policies: tuple = ()
    service_auth: ServiceAuthSettings = ServiceAuthSettings()
    authentication: AuthenticationSettings = AuthenticationSettings()
    max_repair_attempts: int = MAX_REPAIR_ATTEMPTS
    live_latency_thresholds_ms: dict[str, float] = field(default_factory=dict)
    audit_retention_days: int = DEFAULT_AUDIT_RETENTION_DAYS
    audit_max_page_size: int = DEFAULT_AUDIT_MAX_PAGE_SIZE
    event_retention_days: int = DEFAULT_EVENT_RETENTION_DAYS

    def __post_init__(self) -> None:
        mode = self.authentication.mode
        if mode not in {"disabled", "development_headers", "oidc", "trusted_proxy"}:
            raise ValueError(f"Unsupported authentication mode: {mode!r}.")
        if mode == "development_headers" and self.environment.lower() not in {"development", "testing"}:
            raise ValueError("Development-header authentication is restricted to development and tests.")


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


def _resolve_service_auth_settings() -> ServiceAuthSettings:
    return ServiceAuthSettings(
        token=os.getenv("RAGGUARD_SERVICE_TOKEN"),
        application=os.getenv(
            "RAGGUARD_SERVICE_APPLICATION",
            "ragguard",
        ),
        tenant_id=os.getenv(
            "RAGGUARD_SERVICE_TENANT",
            "development",
        ),
    )


def _resolve_authentication_settings(data: dict) -> AuthenticationSettings:
    auth_data = data.get("authentication", {}) or {}
    if not isinstance(auth_data, dict):
        raise ValueError("authentication must be a mapping.")
    mode = os.getenv("RAGGUARD_AUTH_MODE", auth_data.get("mode", "disabled"))
    mode = str(mode).strip().lower()
    if mode not in {"disabled", "development_headers", "oidc", "trusted_proxy"}:
        raise ValueError(f"Unsupported RAGGUARD_AUTH_MODE: {mode!r}.")

    origins = os.getenv("RAGGUARD_FRONTEND_ORIGINS", "")
    frontend_origins = tuple(
        origin.strip().rstrip("/")
        for origin in origins.split(",")
        if origin.strip()
    )
    for origin in frontend_origins:
        parsed_origin = urlparse(origin)
        local_http = parsed_origin.scheme == "http" and parsed_origin.hostname in {"localhost", "127.0.0.1"}
        if (
            origin == "*"
            or parsed_origin.scheme not in {"https", "http"}
            or not parsed_origin.netloc
            or parsed_origin.path not in {"", "/"}
            or parsed_origin.username
            or parsed_origin.password
            or (parsed_origin.scheme != "https" and not local_http)
        ):
            raise ValueError("RAGGUARD_FRONTEND_ORIGINS must contain exact HTTPS origins (localhost HTTP is allowed locally).")
    for origin in frontend_origins:
        parsed_origin = urlparse(origin)
        local_http = parsed_origin.scheme == "http" and parsed_origin.hostname in {"localhost", "127.0.0.1"}
        if (
            origin == "*"
            or parsed_origin.scheme not in {"https", "http"}
            or not parsed_origin.netloc
            or parsed_origin.path not in {"", "/"}
            or parsed_origin.username
            or parsed_origin.password
            or (parsed_origin.scheme != "https" and not local_http)
        ):
            raise ValueError("RAGGUARD_FRONTEND_ORIGINS must contain exact HTTPS origins (localhost HTTP is allowed locally).")
    same_site = os.getenv("RAGGUARD_SESSION_COOKIE_SAMESITE", "lax").strip().lower()
    if same_site not in {"lax", "strict", "none"}:
        raise ValueError("RAGGUARD_SESSION_COOKIE_SAMESITE must be lax, strict, or none.")
    secure = os.getenv("RAGGUARD_SESSION_COOKIE_SECURE", "true").strip().lower() in {"1", "true", "yes", "on"}
    if same_site == "none" and not secure:
        raise ValueError("SameSite=None session cookies require Secure.")
    ttl = int(os.getenv("RAGGUARD_SESSION_TTL_SECONDS", "28800"))
    if not 300 <= ttl <= 86400:
        raise ValueError("RAGGUARD_SESSION_TTL_SECONDS must be between 300 and 86400.")
    token_auth_method = os.getenv("RAGGUARD_OIDC_TOKEN_AUTH_METHOD", "client_secret_basic").strip().lower()
    if token_auth_method not in {"client_secret_basic", "client_secret_post"}:
        raise ValueError("RAGGUARD_OIDC_TOKEN_AUTH_METHOD must be client_secret_basic or client_secret_post.")
    return AuthenticationSettings(
        mode=mode,
        oidc_issuer=(os.getenv("RAGGUARD_OIDC_ISSUER") or "").strip() or None,
        oidc_client_id=os.getenv("RAGGUARD_OIDC_CLIENT_ID"),
        oidc_client_secret=os.getenv("RAGGUARD_OIDC_CLIENT_SECRET"),
        oidc_token_auth_method=token_auth_method,
        oidc_redirect_uri=os.getenv("RAGGUARD_OIDC_REDIRECT_URI"),
        frontend_url=os.getenv("RAGGUARD_FRONTEND_URL"),
        session_secret=os.getenv("RAGGUARD_SESSION_SECRET"),
        session_cookie_name=os.getenv("RAGGUARD_SESSION_COOKIE_NAME", "ragguard_session"),
        session_cookie_secure=secure,
        session_cookie_samesite=same_site,
        session_ttl_seconds=ttl,
        frontend_origins=frontend_origins,
    )


def _resolve_max_repair_attempts(data: dict) -> int:
    value = int(
        os.getenv(
            "RAGGUARD_MAX_REPAIR_ATTEMPTS",
            data.get("max_repair_attempts", MAX_REPAIR_ATTEMPTS),
        )
    )
    if not 0 <= value <= MAX_REPAIR_ATTEMPTS:
        raise ValueError(
            f"max_repair_attempts must be between 0 and {MAX_REPAIR_ATTEMPTS}."
        )
    return value


def _resolve_positive_setting(data: dict, key: str, env_key: str, default: int) -> int:
    value = int(os.getenv(env_key, data.get(key, default)))
    if value < 1:
        raise ValueError(f"{key} must be greater than zero.")
    return value


def _resolve_audit_settings(data: dict) -> dict[str, int]:
    return {
        "audit_retention_days": _resolve_positive_setting(
            data,
            "audit_retention_days",
            "RAGGUARD_AUDIT_RETENTION_DAYS",
            DEFAULT_AUDIT_RETENTION_DAYS,
        ),
        "audit_max_page_size": _resolve_positive_setting(
            data,
            "audit_max_page_size",
            "RAGGUARD_AUDIT_MAX_PAGE_SIZE",
            DEFAULT_AUDIT_MAX_PAGE_SIZE,
        ),
        "event_retention_days": _resolve_positive_setting(
            data,
            "event_retention_days",
            "RAGGUARD_EVENT_RETENTION_DAYS",
            DEFAULT_EVENT_RETENTION_DAYS,
        ),
    }


def _resolve_live_latency_thresholds(data: dict) -> dict[str, float]:
    configured = data.get("live_latency_thresholds_ms", {}) or {}
    if not isinstance(configured, dict):
        raise ValueError("live_latency_thresholds_ms must be a mapping of stages to milliseconds.")

    thresholds: dict[str, float] = {}
    for stage, raw_value in configured.items():
        if not isinstance(stage, str) or not stage.strip() or isinstance(raw_value, bool):
            raise ValueError("Latency stages must be non-empty strings with numeric thresholds.")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Latency threshold for {stage!r} must be numeric.") from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Latency threshold for {stage!r} must be greater than zero.")
        thresholds[stage] = value
    return thresholds


def load_settings(path: str | None = None) -> Settings:
    path = path or os.getenv("RAGGUARD_CONFIG", "configs/development.yaml")
    p = Path(path)
    if not p.exists():
        return Settings(
            environment=os.getenv("RAGGUARD_ENV", "development"),
            llm=_resolve_llm_settings({}),
            service_auth=_resolve_service_auth_settings(),
            authentication=_resolve_authentication_settings({}),
            max_repair_attempts=_resolve_max_repair_attempts({}),
            live_latency_thresholds_ms=_resolve_live_latency_thresholds({}),
            **_resolve_audit_settings({}),
        )
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
    service_auth = _resolve_service_auth_settings()
    environment = os.getenv("RAGGUARD_ENV", str(data.get("environment", "development")))
    if not policies:
        # Keep the default single-tenant workspace visible in the registry too.
        # TenantService has historically supplied this fallback at request time,
        # but an empty policy list meant startup had nothing to bootstrap.
        policies.append(TenantPolicy(
            tenant_id=service_auth.tenant_id,
            application_id=service_auth.application,
            environment=data.get("environment", "development"),
            vector_namespace=service_auth.tenant_id,
            llm=base_llm,
        ))
    return Settings(
        environment=environment,
        top_k=int(data.get("top_k", 5)),
        thresholds=Thresholds(**data.get("thresholds", {})),
        llm=base_llm,
        tenant_policies=tuple(policies),
        service_auth=service_auth,
        authentication=_resolve_authentication_settings(data),
        max_repair_attempts=_resolve_max_repair_attempts(data),
        live_latency_thresholds_ms=_resolve_live_latency_thresholds(data),
        **_resolve_audit_settings(data),
    )
