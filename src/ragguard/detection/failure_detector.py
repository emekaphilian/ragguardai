from uuid import uuid4
from ragguard.common.schemas import FailureEvent
from ragguard.evaluation.thresholds import below_thresholds
from .rules import ORDER, severity_for

class FailureDetector:
    def __init__(self, thresholds):
        self.thresholds = thresholds

    def detect(self, query, metrics):
        flags = below_thresholds(metrics, self.thresholds)
        for mode, field in ORDER:
            if flags[field]:
                score = getattr(metrics, field)
                return FailureEvent(
                    failure_id=str(uuid4()),
                    query=query,
                    failure_type=mode,
                    severity=severity_for(score),
                    metrics=metrics,
                    evidence=[f"{field}={score:.3f} below threshold"],
                )
        return None
