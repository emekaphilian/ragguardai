from __future__ import annotations

import json
import os
from typing import Any

from ragguard.auth.tenant_context import TenantContext
from ragguard.config import LLMSettings, Settings
from ragguard.llm.prompts import build_narration_prompt
from ragguard.llm.providers import AnthropicProvider, CohereProvider, LLMProvider, OllamaProvider, OpenAIProvider
from ragguard.llm.schemas import NarrationResponse


PROVIDER_TYPES: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "cohere": CohereProvider,
    "ollama": OllamaProvider,
}


def _api_key_for(provider: str, settings: LLMSettings) -> str | None:
    if provider == settings.provider and settings.api_key:
        return settings.api_key
    if provider == "ollama":
        return "local"
    return os.getenv({
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "cohere": "COHERE_API_KEY",
    }.get(provider, "")) or None


def get_llm_provider(provider: str, settings: LLMSettings) -> LLMProvider:
    provider_name = provider.lower().strip()
    provider_type = PROVIDER_TYPES.get(provider_name)
    if provider_type is None:
        raise ValueError(f"Unsupported narrator provider: {provider_name}")
    api_key = _api_key_for(provider_name, settings)
    if not api_key:
        raise RuntimeError(f"{provider_name} API key is not configured")
    return provider_type(model=settings.model, api_key=api_key, timeout=settings.timeout)


def _provider_order(settings: LLMSettings) -> tuple[str, ...]:
    return tuple(dict.fromkeys((settings.provider, *settings.fallback_providers)))


def _parse_response(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    return NarrationResponse.model_validate(payload).model_dump()


def generate_llm_narration(page: str, data: dict[str, Any], settings: Settings, context: TenantContext | None = None) -> dict[str, Any]:
    llm_settings = settings.llm
    if context is not None:
        from ragguard.tenants.service import TenantService
        llm_settings = TenantService(settings).llm_settings_for(context)
    if not llm_settings.enabled:
        raise RuntimeError("LLM narration is disabled")

    prompt = build_narration_prompt(page, data)
    failures: list[str] = []
    for provider_name in _provider_order(llm_settings):
        try:
            provider = get_llm_provider(provider_name, llm_settings)
            return _parse_response(provider.generate(prompt))
        except Exception as exc:
            failures.append(f"{provider_name}: {exc}")

    raise RuntimeError("All narrator providers failed: " + "; ".join(failures))
