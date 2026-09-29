from __future__ import annotations

from ragguard.auth.tenant_context import TenantContext
from ragguard.detection.live_detector import LiveFailureDetector
from ragguard.evaluation.live import RAGObservation
from ragguard.evaluation.live_evaluator import LiveEvaluator
from ragguard.repair.repair_policy import EXECUTABLE_REPAIRS


def run_replay(
    *,
    observation: RAGObservation,
    context: TenantContext,
    recovery_service,
) -> dict:
    """Re-evaluate a saved observation and run it through an isolated graph service."""
    evaluation = LiveEvaluator().evaluate(observation)
    failure = LiveFailureDetector().detect(observation, evaluation)

    if not recovery_service.available_repairs <= EXECUTABLE_REPAIRS:
        raise ValueError("Replay service requested an unsupported repair capability.")

    return recovery_service.recover(
        observation=observation,
        context=context,
        evaluation=evaluation,
        failure_event=failure,
    )
