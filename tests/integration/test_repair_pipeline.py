from ragguard.config import Thresholds
from ragguard.common.schemas import EvaluationResult
from ragguard.detection.failure_detector import FailureDetector

def test_repair_pipeline_starts_with_detection():
    metrics = EvaluationResult(
        context_precision=.1,
        context_recall=.1,
        faithfulness=.8,
        answer_relevancy=.8,
        overall_score=.36,
    )
    assert FailureDetector(Thresholds()).detect("q", metrics) is not None
