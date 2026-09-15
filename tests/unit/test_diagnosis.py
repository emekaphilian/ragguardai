from ragguard.common.schemas import EvaluationResult, FailureEvent
from ragguard.common.enums import FailureMode, Severity, RepairType
from ragguard.diagnosis.diagnostic_agent import diagnose

def test_diagnosis():
    failure = FailureEvent(
        failure_id="1",
        query="q",
        failure_type=FailureMode.LOW_CONTEXT_RECALL,
        severity=Severity.HIGH,
        metrics=EvaluationResult(
            context_precision=.8,
            context_recall=.2,
            faithfulness=.8,
            answer_relevancy=.8,
            overall_score=.64,
        ),
    )
    diagnosis = diagnose(failure)
    assert RepairType.HYBRID_RETRIEVAL in diagnosis.recommended_repairs
