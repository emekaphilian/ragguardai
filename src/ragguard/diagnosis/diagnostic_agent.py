from ragguard.common.schemas import DiagnosisResult
from .root_cause import recommended_repairs
from .evidence import build_evidence

def diagnose(failure):
    mode = failure.failure_type.value
    metadata = getattr(failure, "metadata", {})
    confidence = {
        "NO_RETRIEVAL": (
            0.95
            if metadata.get("retrieval_required") is True
            or metadata.get("retrieval_attempted") is True
            else 0.65
        ),
        "GENERATION_FAILURE": 0.95,
        "INFRASTRUCTURE_FAILURE": 0.9,
        "INSUFFICIENT_EVIDENCE": 0.8,
        "LATENCY_ANOMALY": 0.9,
        "WEAK_RETRIEVAL": 0.65,
        "EMBEDDING_DEGRADED": 0.8,
        "DUPLICATE_CONTEXT": 0.9,
    }.get(mode, 0.6)
    return DiagnosisResult(
        failure_id=failure.failure_id,
        root_cause=failure.failure_type,
        confidence=confidence,
        evidence=build_evidence(failure),
        recommended_repairs=recommended_repairs(failure.failure_type),
    )
