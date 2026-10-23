def build_evidence(failure):
    evidence = list(failure.evidence)
    metadata = getattr(failure, "metadata", {})
    for field in (
        "retrieval_required",
        "retrieval_attempted",
        "retrieval_outcome",
        "evidence_sufficient",
        "generation_status",
        "failed_stage",
        "error_code",
    ):
        value = metadata.get(field)
        if value is not None:
            evidence.append(f"{field}={value}")
    for stage, duration in sorted(metadata.get("stage_timings_ms", {}).items()):
        evidence.append(f"{stage}_latency_ms={duration}")

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
