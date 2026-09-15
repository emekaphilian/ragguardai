from ragguard.config import Thresholds
from ragguard.common.schemas import EvaluationResult
from ragguard.common.enums import FailureMode
from ragguard.detection.failure_detector import FailureDetector

def test_detector_priority():
    metrics = EvaluationResult(
        context_precision=.2,
        context_recall=.2,
        faithfulness=.9,
        answer_relevancy=.9,
        overall_score=.48,
    )
    failure = FailureDetector(Thresholds()).detect("q", metrics)
    assert failure.failure_type == FailureMode.LOW_CONTEXT_RECALL
