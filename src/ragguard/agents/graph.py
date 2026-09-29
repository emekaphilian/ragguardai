from __future__ import annotations

import asyncio
from uuid import uuid4

from ragguard.agents.diagnosis_agent import diagnosis_node
from ragguard.agents.detector_agent import detector_node
from ragguard.agents.repair_agent import plan_repair_node, repair_node
from ragguard.agents.state import RAGGuardState
from ragguard.agents.validation_agent import (
    escalate_node,
    promote_node,
    rollback_node,
    validation_node,
)
from ragguard.config import MAX_REPAIR_ATTEMPTS, load_settings
from ragguard.repair.repair_policy import (
    EXECUTABLE_REPAIRS,
    choose_executable_repair,
)
from ragguard.observability.recovery_audit import (
    RecoveryAuditRecord,
    RecoveryEventType,
)
from ragguard.events.recovery_events import RecoveryEvent


def build_langgraph(
    detector,
    diagnosis_fn,
    repair_engine,
    store,
    evaluator,
    relevant_ids,
    answer,
    max_repair_attempts: int | None = None,
    available_repairs=None,
    event_bus=None,
):
    """Build the bounded reliability workflow around existing RAGGuard services."""
    if max_repair_attempts is None:
        max_repair_attempts = load_settings().max_repair_attempts
    if not 0 <= max_repair_attempts <= MAX_REPAIR_ATTEMPTS:
        raise ValueError(
            f"max_repair_attempts must be between 0 and {MAX_REPAIR_ATTEMPTS}."
        )
    available_repairs = (
        EXECUTABLE_REPAIRS
        if available_repairs is None
        else frozenset(available_repairs) & EXECUTABLE_REPAIRS
    )

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph is required for the RAGGuard repair workflow."
        ) from exc

    def state_from(values) -> RAGGuardState:
        return values if isinstance(values, RAGGuardState) else RAGGuardState(**values)

    def result(state: RAGGuardState, node: str):
        state.completed_nodes.append(node)
        return vars(state)

    def publish_audit_event(event):
        if event_bus is None:
            return

        recovery_event = RecoveryEvent.from_audit_event(event)

        async def publish():
            await event_bus.publish(recovery_event)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(publish())
        else:
            loop.create_task(publish())

    def record_event(state: RAGGuardState, event_type, **kwargs):
        event = state.recovery_audit.add_event(event_type, **kwargs)
        publish_audit_event(event)

    def complete_audit(state: RAGGuardState, status: str, **kwargs):
        if state.recovery_audit is None:
            return
        start = len(state.recovery_audit.events)
        state.recovery_audit.complete(status, **kwargs)
        for event in state.recovery_audit.events[start:]:
            publish_audit_event(event)

    def initialize_audit(state: RAGGuardState) -> None:
        if state.recovery_audit is not None:
            return

        state.graph_run_id = str(uuid4())
        failure = state.failure_event
        failure_type = getattr(failure, "failure_type", None)
        failure_type = getattr(failure_type, "value", failure_type)
        observation = state.observation
        source = getattr(observation, "source", None)
        observation_snapshot = None
        if observation is not None:
            model_dump = getattr(observation, "model_dump", None)
            observation_snapshot = (
                model_dump(mode="json")
                if callable(model_dump)
                else observation
                if isinstance(observation, dict)
                else None
            )
        original_score = getattr(state.original_metrics, "overall_score", None)

        audit = RecoveryAuditRecord.create(
            graph_run_id=state.graph_run_id,
            failure_id=getattr(failure, "failure_id", None),
            failure_type=failure_type,
            application_id=getattr(source, "application_id", None),
            environment=getattr(source, "environment", None),
            tenant_id=None,
            ragguard_tenant_id=(
                state.context.tenant_id if state.context is not None else None
            ),
            original_score=original_score,
            observation_snapshot=observation_snapshot,
        )
        state.recovery_id = audit.recovery_id
        state.recovery_audit = audit
        record_event(state, RecoveryEventType.RUN_STARTED, status="started")

    def evaluate(values):
        state = state_from(values)
        if state.evaluation_result is None and state.retrieval_result is None:
            raise ValueError("RAGGuardState requires retrieval_result.")
        if state.evaluation_result is None:
            state.evaluation_result = evaluator.evaluate(
                state.query, answer, state.retrieval_result, relevant_ids
            )
        state.original_retrieval = state.retrieval_result
        state.original_metrics = state.evaluation_result
        state.status = "evaluated"
        initialize_audit(state)
        if state.recovery_audit is not None:
            state.recovery_audit.original_score = getattr(
                state.original_metrics,
                "overall_score",
                None,
            )
        return result(state, "evaluate")

    def detect(values):
        state = state_from(values)
        if state.failure_event is None:
            if detector is None:
                raise ValueError("Graph requires a detector or pre-detected failure.")
            state = detector_node(state, detector)
        else:
            state.status = "failed"
        initialize_audit(state)
        if state.recovery_audit is not None:
            failure = state.failure_event
            failure_type = getattr(failure, "failure_type", None)
            failure_type = getattr(failure_type, "value", failure_type)
            state.recovery_audit.failure_id = getattr(failure, "failure_id", None)
            state.recovery_audit.failure_type = failure_type
            if failure is not None:
                record_event(
                    state,
                    RecoveryEventType.FAILURE_DETECTED,
                    status="failed",
                    reason=failure_type,
                )
            else:
                complete_audit(
                    state,
                    "healthy",
                    final_score=getattr(state.evaluation_result, "overall_score", None),
                    improvement=0.0,
                )
        return result(state, "detect")

    def diagnose(values):
        state = diagnosis_node(state_from(values), diagnosis_fn)
        if state.recovery_audit is not None:
            root_cause = getattr(state.diagnosis, "root_cause", None)
            root_cause = getattr(root_cause, "value", root_cause)
            record_event(
                state,
                RecoveryEventType.DIAGNOSIS_COMPLETED,
                status="diagnosed",
                reason=str(root_cause) if root_cause is not None else None,
                metadata={"confidence": getattr(state.diagnosis, "confidence", None)},
            )
        return result(state, "diagnose")

    def plan_repair(values):
        state = state_from(values)
        if len(state.attempted_repairs) >= max_repair_attempts:
            state.repair_plan = None
            state.status = "escalated"
            state.escalation_reason = "Maximum repair attempts reached."
        else:
            plan_repair_node(state, available_repairs)
            # The node selects only strategies with a real implementation.
            if state.repair_plan is None:
                state.status = "escalated"
                state.escalation_reason = "No available repair strategy is permitted."
        if state.recovery_audit is not None:
            strategy = getattr(state.repair_plan, "value", state.repair_plan)
            record_event(
                state,
                RecoveryEventType.REPAIR_PLANNED,
                attempt=(
                    len(state.attempted_repairs) + 1
                    if state.repair_plan is not None
                    else None
                ),
                strategy=str(strategy) if strategy is not None else None,
                status="planned" if state.repair_plan is not None else "unavailable",
                reason=state.escalation_reason,
            )
        return result(state, "plan_repair")

    def repair(values):
        state = state_from(values)
        if state.repair_plan is None:
            raise ValueError("Repair node requires a permitted repair plan.")
        attempt_number = len(state.attempted_repairs) + 1
        strategy = getattr(state.repair_plan, "value", state.repair_plan)
        if state.recovery_audit is not None:
            record_event(
                state,
                RecoveryEventType.REPAIR_STARTED,
                attempt=attempt_number,
                strategy=str(strategy) if strategy is not None else None,
                status="started",
            )
        repair_node(
            state,
            repair_engine,
            store,
            evaluator,
            relevant_ids,
            answer,
            available_repairs,
        )
        if state.repair_result is None:
            raise RuntimeError("Repair engine did not return a repair result.")
        state.repair_attempts.append({
            "strategy": state.repair_result.repair_type.value,
            "status": "attempted",
            "improvement": None,
        })
        if state.recovery_audit is not None:
            state.recovery_audit.attempts.append(state.repair_attempts[-1].copy())
            record_event(
                state,
                RecoveryEventType.REPAIR_COMPLETED,
                attempt=attempt_number,
                strategy=str(strategy) if strategy is not None else None,
                status="completed",
            )
        state.candidate_retrieval = state.repair_result.after_retrieval
        state.status = "repair_candidate"
        return result(state, "repair")

    def re_evaluate(values):
        state = state_from(values)
        if state.candidate_retrieval is None or state.repair_result is None:
            raise ValueError("Re-evaluation requires a candidate retrieval result.")
        state.candidate_metrics = evaluator.evaluate(
            state.query, answer, state.candidate_retrieval, relevant_ids
        )
        state.repair_result.after_metrics = state.candidate_metrics
        state.repair_result.improvement = (
            state.candidate_metrics.overall_score
            - state.repair_result.before_metrics.overall_score
        )
        state.repair_result.status = "candidate"
        if state.repair_attempts:
            state.repair_attempts[-1]["improvement"] = state.repair_result.improvement
        if state.recovery_audit is not None and state.recovery_audit.attempts:
            state.recovery_audit.attempts[-1]["improvement"] = (
                state.repair_result.improvement
            )
        return result(state, "re_evaluate")

    def validate(values):
        state = validation_node(state_from(values), repair_engine)
        if state.recovery_audit is not None:
            repair = state.repair_result
            validation = state.validation_result
            record_event(
                state,
                RecoveryEventType.VALIDATION_COMPLETED,
                attempt=len(state.attempted_repairs),
                strategy=getattr(getattr(repair, "repair_type", None), "value", None),
                status="validated",
                before_score=getattr(getattr(repair, "before_metrics", None), "overall_score", None),
                after_score=getattr(getattr(repair, "after_metrics", None), "overall_score", None),
                improvement=getattr(repair, "improvement", None),
                validation_valid=getattr(validation, "valid", None),
                validation_improved=getattr(validation, "improved", None),
            )
        return result(state, "validate")

    def promote(values):
        state = promote_node(state_from(values))
        if state.repair_result is not None:
            state.repair_result.status = "promoted"
        if state.repair_attempts:
            state.repair_attempts[-1]["status"] = "promoted"
        if state.recovery_audit is not None:
            if state.recovery_audit.attempts:
                state.recovery_audit.attempts[-1]["status"] = "promoted"
            final_score = getattr(
                getattr(state.repair_result, "after_metrics", None),
                "overall_score",
                None,
            )
            complete_audit(
                state,
                "promoted",
                final_score=final_score,
                improvement=getattr(state.repair_result, "improvement", None),
            )
        return result(state, "promote")

    def rollback(values):
        state = rollback_node(state_from(values))
        if state.repair_result is not None:
            state.repair_result.status = "rolled_back"
        if state.repair_attempts:
            state.repair_attempts[-1]["status"] = "rolled_back"
        if state.recovery_audit is not None:
            if state.recovery_audit.attempts:
                state.recovery_audit.attempts[-1]["status"] = "rolled_back"
            repair = state.repair_result
            record_event(
                state,
                RecoveryEventType.ROLLBACK,
                attempt=len(state.attempted_repairs),
                strategy=getattr(getattr(repair, "repair_type", None), "value", None),
                status="rolled_back",
                before_score=getattr(getattr(repair, "before_metrics", None), "overall_score", None),
                after_score=getattr(getattr(repair, "after_metrics", None), "overall_score", None),
                improvement=getattr(repair, "improvement", None),
            )
        return result(state, "rollback")

    def escalate(values):
        state = escalate_node(state_from(values))
        if state.escalation_reason is None:
            state.escalation_reason = (
                "Maximum repair attempts reached."
                if len(state.attempted_repairs) >= max_repair_attempts
                else "No further permitted repair strategy is available."
            )
        if state.recovery_audit is not None:
            original_score = getattr(state.original_metrics, "overall_score", None)
            complete_audit(
                state,
                "escalated",
                final_score=original_score,
                improvement=0.0 if original_score is not None else None,
            )
        return result(state, "escalate")

    def after_rollback(values):
        state = state_from(values)
        if len(state.attempted_repairs) >= max_repair_attempts:
            return "escalate"
        if choose_executable_repair(
            state.diagnosis,
            state.attempted_repairs,
            available_repairs,
        ):
            return "plan_repair"
        return "escalate"

    graph = StateGraph(RAGGuardState)
    graph.add_node("evaluate", evaluate)
    graph.add_node("detect", detect)
    graph.add_node("diagnose", diagnose)
    graph.add_node("plan_repair", plan_repair)
    graph.add_node("repair", repair)
    graph.add_node("re_evaluate", re_evaluate)
    graph.add_node("validate", validate)
    graph.add_node("promote", promote)
    graph.add_node("rollback", rollback)
    graph.add_node("escalate", escalate)

    graph.add_edge(START, "evaluate")
    graph.add_edge("evaluate", "detect")
    graph.add_conditional_edges(
        "detect",
        lambda values: "diagnose" if state_from(values).failure_event else "end",
        {"diagnose": "diagnose", "end": END},
    )
    graph.add_edge("diagnose", "plan_repair")
    graph.add_conditional_edges(
        "plan_repair",
        lambda values: "repair" if state_from(values).repair_plan else "escalate",
        {"repair": "repair", "escalate": "escalate"},
    )
    graph.add_edge("repair", "re_evaluate")
    graph.add_edge("re_evaluate", "validate")
    graph.add_conditional_edges(
        "validate",
        lambda values: (
            "promote"
            if state_from(values).validation_result
            and state_from(values).validation_result.valid
            and state_from(values).validation_result.improved
            else "rollback"
        ),
        {"promote": "promote", "rollback": "rollback"},
    )
    graph.add_edge("promote", END)
    graph.add_conditional_edges(
        "rollback",
        after_rollback,
        {"plan_repair": "plan_repair", "escalate": "escalate"},
    )
    graph.add_edge("escalate", END)
    return graph.compile()


def run_sequential(
    state,
    detector,
    diagnosis_fn,
    repair_engine,
    store,
    evaluator,
    relevant_ids,
    answer,
    max_repair_attempts: int | None = None,
):
    """Compatibility wrapper; all workflow decisions run through LangGraph."""
    if max_repair_attempts is None:
        max_repair_attempts = load_settings().max_repair_attempts
    graph = build_langgraph(
        detector,
        diagnosis_fn,
        repair_engine,
        store,
        evaluator,
        relevant_ids,
        answer,
        max_repair_attempts=max_repair_attempts,
    )
    final_values = graph.invoke(
        state,
        config={"recursion_limit": max(25, max_repair_attempts * 8 + 12)},
    )
    if isinstance(final_values, dict):
        for field_name, value in final_values.items():
            if hasattr(state, field_name):
                setattr(state, field_name, value)
    if state.status == "promoted":
        state.status = "repaired"
    return state
