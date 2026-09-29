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
            return self._event(
                observation,
                evaluation,
                FailureMode.NO_RETRIEVAL,
                Severity.HIGH,
                ["No chunks were retrieved."],
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
                "source": observation.source.model_dump(),
            },
        )
