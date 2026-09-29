def build_evidence(failure):
    evidence = list(failure.evidence)
    metrics = getattr(failure, "metrics", None)
    if metrics is not None and hasattr(metrics, "overall_score"):
        evidence.append(f"overall_score={metrics.overall_score:.3f}")

    evaluation = getattr(failure, "evaluation", None)
    if evaluation is not None:
        evidence.append(f"live_status={evaluation.status}")
        evidence.append(f"retrieved_count={evaluation.retrieved_count}")
        if evaluation.top_score is not None:
            evidence.append(f"top_score={evaluation.top_score:.3f}")
        evidence.append(f"duplicate_ratio={evaluation.duplicate_ratio:.3f}")

    return evidence
