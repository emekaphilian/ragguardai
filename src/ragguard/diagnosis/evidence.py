def build_evidence(failure):
    return failure.evidence + [f"overall_score={failure.metrics.overall_score:.3f}"]
