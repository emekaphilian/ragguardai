import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ragguard.config import load_settings
from ragguard.common.schemas import EvaluationResult
from ragguard.detection.failure_detector import FailureDetector

def main():
    detector = FailureDetector(load_settings().thresholds)
    metrics = EvaluationResult(
        context_precision=.40,
        context_recall=.30,
        faithfulness=.90,
        answer_relevancy=.80,
        citation_accuracy=.40,
        overall_score=.56,
    )
    failure = detector.detect("demo query", metrics)
    print(failure.model_dump_json(indent=2) if failure else "No failure detected.")

if __name__ == "__main__":
    main()
