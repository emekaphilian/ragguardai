from __future__ import annotations

from ragguard.auth.tenant_context import TenantContext
from ragguard.config import load_settings
from ragguard.detection.live_detector import LiveFailureDetector
from ragguard.evaluation.live import RAGObservation
from ragguard.evaluation.live_evaluator import LiveEvaluator
from ragguard.repair.repair_policy import EXECUTABLE_REPAIRS
from ragguard.tenants.application_registration import ApplicationRegistration


def run_replay(
    *,
    observation: RAGObservation,
    context: TenantContext,
    application_registration: ApplicationRegistration | None = None,
    recovery_service,
) -> dict:
    """Re-evaluate a saved observation and run it through an isolated graph service."""
    evaluation = LiveEvaluator(
        latency_thresholds_ms=load_settings().live_latency_thresholds_ms,
    ).evaluate(observation)
    failure = LiveFailureDetector().detect(observation, evaluation)

    if not recovery_service.available_repairs <= EXECUTABLE_REPAIRS:
        raise ValueError("Replay service requested an unsupported repair capability.")

    return recovery_service.recover(
        observation=observation,
        context=context,
        application_registration=application_registration,
        evaluation=evaluation,
        failure_event=failure,
    )
