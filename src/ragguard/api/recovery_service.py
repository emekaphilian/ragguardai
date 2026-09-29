from __future__ import annotations

from collections.abc import Callable, Iterable

from ragguard.agents.graph import build_langgraph
from ragguard.auth.tenant_context import TenantContext
from ragguard.diagnosis.diagnostic_agent import diagnose
from ragguard.evaluation.live import LiveEvaluation, RAGObservation
from ragguard.observability.recovery_repository import (
    InMemoryRecoveryAuditRepository,
    RecoveryAuditRepository,
)
from ragguard.events.bus import RecoveryEventBus
from ragguard.repair.repair_policy import EXECUTABLE_REPAIRS

from .observation_recovery import build_observation_state


class ObservationRecoveryService:
    """Bridge an observation to the internal, capability-bounded graph."""

    def __init__(
        self,
        *,
        detector=None,
        diagnosis_fn: Callable = diagnose,
        repair_engine=None,
        store=None,
        evaluator=None,
        relevant_ids: Iterable[str] = (),
        retrieval_builder: Callable | None = None,
        available_repairs: Iterable | None = None,
        max_repair_attempts: int | None = None,
        recovery_repository: RecoveryAuditRepository | None = None,
        event_bus: RecoveryEventBus | None = None,
        isolated_replay: bool = False,
    ):
        self.detector = detector
        self.diagnosis_fn = diagnosis_fn
        self.repair_engine = repair_engine
        self.store = store
        self.evaluator = evaluator
        self.relevant_ids = set(relevant_ids)
        self.retrieval_builder = retrieval_builder
        self.max_repair_attempts = max_repair_attempts
        self.recovery_repository = (
            recovery_repository or InMemoryRecoveryAuditRepository()
        )
        self.event_bus = event_bus
        self.isolated_replay = isolated_replay

        repair_capability_ready = all((
            repair_engine,
            store,
            evaluator,
            retrieval_builder,
        ))
        if available_repairs is None:
            self.available_repairs = (
                EXECUTABLE_REPAIRS if repair_capability_ready else frozenset()
            )
        else:
            self.available_repairs = frozenset(available_repairs) & EXECUTABLE_REPAIRS
            if self.available_repairs and not repair_capability_ready:
                raise ValueError(
                    "Repair capabilities require a repair engine, store, evaluator, "
                    "and retrieval builder."
                )

    def recover(
        self,
        *,
        observation: RAGObservation,
        context: TenantContext,
        evaluation: LiveEvaluation,
        failure_event,
    ) -> dict:
        retrieval_result = None
        graph_evaluator = self.evaluator
        graph_metrics = evaluation

        if self.available_repairs:
            retrieval_result = self.retrieval_builder(observation, context)
            if retrieval_result is None:
                raise ValueError("Retrieval builder returned no repair input.")
            graph_metrics = self.evaluator.evaluate(
                observation.query,
                observation.answer or "",
                retrieval_result,
                self.relevant_ids,
            )

        state = build_observation_state(
            observation=observation,
            context=context,
            retrieval_result=retrieval_result,
            evaluation_result=graph_metrics,
            failure_event=failure_event,
        )
        graph = build_langgraph(
            detector=self.detector,
            diagnosis_fn=self.diagnosis_fn,
            repair_engine=self.repair_engine,
            store=self.store,
            evaluator=graph_evaluator,
            relevant_ids=self.relevant_ids,
            answer=observation.answer or "",
            max_repair_attempts=self.max_repair_attempts,
            available_repairs=self.available_repairs,
            event_bus=self.event_bus,
        )
        result = graph.invoke(state)
        audit = result.get("recovery_audit") if isinstance(result, dict) else None
        if audit is not None:
            self.recovery_repository.save(audit)
        return result
