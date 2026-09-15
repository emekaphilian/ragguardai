from ragguard.common.schemas import DiagnosisResult
from .root_cause import recommended_repairs
from .evidence import build_evidence

def diagnose(failure):
    return DiagnosisResult(
        failure_id=failure.failure_id,
        root_cause=failure.failure_type,
        confidence=0.95,
        evidence=build_evidence(failure),
        recommended_repairs=recommended_repairs(failure.failure_type),
    )
