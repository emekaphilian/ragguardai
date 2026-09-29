from __future__ import annotations

from ragguard.agents.state import RAGGuardState
from ragguard.auth.tenant_context import TenantContext
from ragguard.detection.live_failure import LiveFailureEvent
from ragguard.evaluation.live import LiveEvaluation, RAGObservation


def build_observation_state(
    *,
    observation: RAGObservation,
    context: TenantContext,
    retrieval_result,
    evaluation_result: LiveEvaluation,
    failure_event: LiveFailureEvent,
) -> RAGGuardState:
    """Convert the external contract into the internal graph state."""
    return RAGGuardState(
        query=observation.query,
        context=context,
        observation=observation,
        retrieval_result=retrieval_result,
        evaluation_result=evaluation_result,
        failure_event=failure_event,
        status="evaluated",
    )


def build_recovery_response(state) -> dict:
    """Project internal graph state onto the stable public recovery contract."""
    def get_value(name, default=None):
        if isinstance(state, dict):
            return state.get(name, default)
        return getattr(state, name, default)

    failure = get_value("failure_event")
    original_metrics = get_value("original_metrics")
    final_metrics = get_value("evaluation_result")
    if get_value("status") == "escalated" and get_value("repair_attempts"):
        final_metrics = original_metrics

    original_score = getattr(original_metrics, "overall_score", None)
    final_score = getattr(final_metrics, "overall_score", None)
    improvement = (
        final_score - original_score
        if original_score is not None and final_score is not None
        else None
    )

    failure_type = getattr(failure, "failure_type", None)
    failure_type = getattr(failure_type, "value", failure_type)

    return {
        "status": get_value("status", "unknown"),
        "recovery_id": get_value("recovery_id"),
        "graph_run_id": get_value("graph_run_id"),
        "failure_detected": failure is not None,
        "failure_type": failure_type,
        "attempts": get_value("repair_attempts", []),
        "original_score": original_score,
        "final_score": final_score,
        "improvement": improvement,
        "completed_nodes": list(get_value("completed_nodes", [])),
        "escalation_reason": get_value("escalation_reason"),
    }
