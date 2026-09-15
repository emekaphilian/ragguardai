from ragguard.common.enums import FailureMode, Severity

ORDER = [
    (FailureMode.LOW_CONTEXT_RECALL, "context_recall"),
    (FailureMode.LOW_CONTEXT_PRECISION, "context_precision"),
    (FailureMode.LOW_FAITHFULNESS, "faithfulness"),
    (FailureMode.LOW_ANSWER_RELEVANCY, "answer_relevancy"),
]

def severity_for(score):
    if score < 0.35:
        return Severity.CRITICAL
    if score < 0.55:
        return Severity.HIGH
    if score < 0.70:
        return Severity.MEDIUM
    return Severity.LOW
