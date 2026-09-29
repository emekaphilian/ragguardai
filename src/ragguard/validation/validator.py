from ragguard.common.schemas import RepairResult, ValidationResult


def validate_repair(result: RepairResult) -> ValidationResult:
    """Compare evaluated before/after scores; success means measurable gain."""
    if result.before_metrics is None or result.after_metrics is None:
        return ValidationResult(
            valid=False,
            improved=False,
            score_delta=0.0,
            message="Repair cannot be validated without before and after metrics.",
        )

    delta = round(
        result.after_metrics.overall_score - result.before_metrics.overall_score,
        10,
    )
    improved = delta > 0.0
    return ValidationResult(
        valid=delta >= 0.0,
        improved=improved,
        score_delta=delta,
        message=(
            "Repair improved evaluation score."
            if improved
            else "Repair did not improve the score."
        ),
    )
