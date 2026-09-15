from ragguard.common.schemas import EvaluationResult
from ragguard.config import Thresholds
from ragguard.detection.failure_detector import FailureDetector

def test_low_score_is_failure():
    metrics = EvaluationResult(
        context_precision=.1,
        context_recall=.1,
        faithfulness=.1,
        answer_relevancy=.1,
        overall_score=.1,
    )
    assert FailureDetector(Thresholds()).detect("q", metrics) is not None
