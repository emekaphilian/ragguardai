from __future__ import annotations

from uuid import uuid4

from ragguard.common.enums import FailureMode, Severity
from ragguard.evaluation.live import LiveEvaluation, RAGGuardObservation

from .live_failure import LiveFailureEvent


class LiveFailureDetector:
    """Detect retrieval failures from observable live signals."""

    def detect(
        self,
        observation: RAGGuardObservation,
        evaluation: LiveEvaluation,
    ) -> LiveFailureEvent | None:
        signals = evaluation.signals

        if signals["no_retrieval"]:
            outcome = evaluation.retrieval_outcome
            evidence = {
                "not_attempted": "Retrieval was required but was not attempted.",
                "no_results": "Retrieval was attempted but returned no chunks.",
                "unknown": "No chunks were reported for a request that required retrieval.",
            }.get(outcome, "No chunks were retrieved.")
            return self._event(
                observation,
                evaluation,
                FailureMode.NO_RETRIEVAL,
                Severity.HIGH,
                [evidence],
            )

        if signals["infrastructure_failed"]:
            return self._event(
                observation,
                evaluation,
                FailureMode.INFRASTRUCTURE_FAILURE,
                Severity.HIGH,
                [
                    f"An infrastructure failure was reported at "
                    f"{observation.failed_stage}."
                ],
            )

        if signals["retrieval_failed"] and not signals["no_retrieval"]:
            evidence = ["The source application reported a retrieval-stage failure."]
            if observation.error_code:
                evidence.append(f"error_code={observation.error_code}")
            return self._event(
                observation,
                evaluation,
                FailureMode.RETRIEVAL_FAILURE,
                Severity.HIGH,
                evidence,
            )

        if signals["generation_failed"]:
            return self._event(
                observation,
                evaluation,
                FailureMode.GENERATION_FAILURE,
                Severity.HIGH,
                ["The source application reported generation failure."],
            )

        if signals["evidence_insufficient"]:
            return self._event(
                observation,
                evaluation,
                FailureMode.INSUFFICIENT_EVIDENCE,
                Severity.MEDIUM,
                ["The source application marked retrieved evidence insufficient."],
            )

        if signals["latency_anomaly"]:
            return self._event(
                observation,
                evaluation,
                FailureMode.LATENCY_ANOMALY,
                Severity.MEDIUM,
                [
                    f"{evaluation.slow_stage} latency="
                    f"{evaluation.slow_stage_latency_ms:.1f}ms exceeded its "
                    "configured threshold."
                ],
            )

        if signals["duplicate_context"]:
            return self._event(
                observation,
                evaluation,
                FailureMode.DUPLICATE_CONTEXT,
                Severity.MEDIUM,
                [f"Duplicate ratio={evaluation.duplicate_ratio:.3f}."],
            )

        if signals["embedding_degraded"]:
            return self._event(
                observation,
                evaluation,
                FailureMode.EMBEDDING_DEGRADED,
                Severity.MEDIUM,
                ["Embedding retrieval used a degraded/fallback path."],
            )

        if signals["weak_retrieval"]:
            return self._event(
                observation,
                evaluation,
                FailureMode.WEAK_RETRIEVAL,
                Severity.MEDIUM,
                [
                    f"Top retrieval score={evaluation.top_score:.3f} "
                    "below the live retrieval threshold."
                ],
            )

        return None

    @staticmethod
    def _event(
        observation: RAGGuardObservation,
        evaluation: LiveEvaluation,
        failure_type: FailureMode,
        severity: Severity,
        evidence: list[str],
    ) -> LiveFailureEvent:
        return LiveFailureEvent(
            contract_version=observation.contract_version,
            source=observation.source,
            failure_id=str(uuid4()),
            query=observation.query,
            failure_type=failure_type,
            severity=severity,
            evaluation=evaluation,
            evidence=evidence,
            metadata={
                **observation.metadata,
                "contract_version": observation.contract_version,
                "source": observation.source.model_dump(exclude_none=True),
                "request_id": observation.request_id,
                "retrieval_required": observation.retrieval_required,
                "retrieval_attempted": observation.retrieval_attempted,
                "retrieval_outcome": evaluation.retrieval_outcome,
                "stage_timings_ms": observation.stage_timings_ms,
                "evidence_sufficient": observation.evidence_sufficient,
                "generation_status": observation.generation_status,
                "failed_stage": observation.failed_stage,
                "error_code": observation.error_code,
            },
        )
