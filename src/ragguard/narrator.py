from __future__ import annotations

from typing import Any

from ragguard.config import LLMSettings, Settings, load_settings
from ragguard.auth.tenant_context import TenantContext
from ragguard.llm.client import generate_llm_narration
from ragguard.llm.schemas import NarrationResponse


def pct(value: Any) -> str:
    return f"{round(float(value) * 100)}%"


def has_narratable_metrics(data: dict[str, Any]) -> bool:
    """Only narrate measured telemetry, never empty dashboard scaffolding."""
    metrics = data.get("metrics", data)
    return any(
        isinstance(metrics.get(field), (int, float)) and not isinstance(metrics.get(field), bool)
        for field in ("context_precision", "context_recall", "faithfulness", "answer_relevancy", "citation_accuracy", "failure_rate", "repair_success_rate")
    )


def deterministic_narration(page: str, data: dict[str, Any]) -> dict[str, Any]:
    m = data.get("metrics", data)
    recall = m.get("context_recall", m.get("recall"))
    faith = m.get("faithfulness")
    repair = m.get("repair_success_rate", m.get("repair_success"))
    failure = m.get("failure_rate")
    warnings: list[str] = []
    bullets: list[str] = []

    if recall is not None:
        bullets.append(f"The system is finding about {pct(recall)} of the information it needs.")
        if float(recall) < 0.80:
            warnings.append("Some questions may be missing useful information.")
    if faith is not None:
        bullets.append(f"About {pct(faith)} of answers are supported by the information found.")
        if float(faith) < 0.80:
            warnings.append("Some answers may need closer checking against the source material.")
    if repair is not None:
        bullets.append(f"Automatic fixes are succeeding about {pct(repair)} of the time.")
    if failure is not None:
        bullets.append(f"About {pct(failure)} of recent requests needed attention.")
        if float(failure) >= 0.20:
            warnings.append("The number of requests needing attention is higher than normal.")
    return {
        "title": f"{page} — plain-language summary",
        "summary": (
            "There are a few areas worth watching. The technical details are available below, but the main point is that the system may need attention."
            if warnings
            else "The system is operating normally overall. Nothing here suggests an immediate problem."
        ),
        "bullets": bullets + warnings[:1],
        "tone": "warn" if warnings else "good",
    }


def generate_narration(page: str, data: dict[str, Any], settings: Settings | None = None, context: TenantContext | None = None) -> dict[str, Any]:
    if not has_narratable_metrics(data):
        return {"available": False}

    settings = settings or load_settings()
    fallback = deterministic_narration(page, data)

    llm_enabled = settings.llm.enabled
    if context is not None:
        from ragguard.tenants.service import TenantService
        llm_enabled = TenantService(settings).llm_settings_for(context).enabled
    if not llm_enabled:
        return {"available": True, **fallback}

    try:
        llm_payload = generate_llm_narration(page, data, settings, context=context)
        validated = NarrationResponse.model_validate(llm_payload)
        return {"available": True, **validated.model_dump()}
    except Exception:
        return {"available": True, **fallback}


def narrate(page: str, data: dict[str, Any], settings: Settings | None = None, context: TenantContext | None = None) -> dict[str, Any]:
    return generate_narration(page, data, settings=settings, context=context)
