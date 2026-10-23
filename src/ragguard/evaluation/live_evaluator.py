from __future__ import annotations

from collections.abc import Mapping
import math

from .live import LiveEvaluation, RAGGuardObservation

DEFAULT_WEAK_TOP_SCORE = 0.35
DEFAULT_AMBIGUOUS_MARGIN = 0.05
DEFAULT_DUPLICATE_RATIO = 0.5


class LiveEvaluator:
    """Evaluate observable retrieval health without requiring ground truth."""

    def __init__(
        self,
        weak_top_score: float = DEFAULT_WEAK_TOP_SCORE,
        ambiguous_margin: float = DEFAULT_AMBIGUOUS_MARGIN,
        duplicate_ratio: float = DEFAULT_DUPLICATE_RATIO,
        latency_thresholds_ms: Mapping[str, float] | None = None,
    ):
        self.weak_top_score = weak_top_score
        self.ambiguous_margin = ambiguous_margin
        self.duplicate_ratio = duplicate_ratio
        self.latency_thresholds_ms = dict(latency_thresholds_ms or {})
        if any(
            not math.isfinite(value) or value <= 0
            for value in self.latency_thresholds_ms.values()
        ):
            raise ValueError("Latency thresholds must be greater than zero.")

    def evaluate(self, observation: RAGGuardObservation) -> LiveEvaluation:
        chunks = observation.retrieved_chunks
        scores = sorted(
            (chunk.score for chunk in chunks),
            reverse=True,
        )

        retrieved_count = len(chunks)
        top_score = scores[0] if scores else None
        score_margin = (
            scores[0] - scores[1]
            if len(scores) >= 2
            else None
        )
        duplicate_ratio = self._duplicate_ratio(chunks)

        retrieval_outcome = self._retrieval_outcome(observation)
        no_retrieval = self._is_retrieval_failure(observation, retrieval_outcome)
        weak_retrieval = (
            top_score is not None
            and top_score < self.weak_top_score
        )
        duplicate_context = duplicate_ratio >= self.duplicate_ratio
        embedding_degraded = (
            observation.embedding_degraded
            or observation.embedding_fallback
            or observation.embedding_failure
            or observation.failed_stage == "embedding"
        )
        latency_anomaly, slow_stage, slow_stage_latency_ms = (
            self._slow_stage(observation)
        )
        generation_failed = observation.generation_status == "failed"
        infrastructure_failed = observation.failed_stage in {
            "database",
            "external_service",
        }
        retrieval_failed = observation.failed_stage == "retrieval"
        evidence_insufficient = observation.evidence_sufficient is False

        if no_retrieval:
            status = "FAILURE"
        elif (
            weak_retrieval
            or duplicate_context
            or embedding_degraded
            or latency_anomaly
            or generation_failed
            or infrastructure_failed
            or retrieval_failed
            or evidence_insufficient
        ):
            status = "DEGRADED"
        else:
            status = "HEALTHY"

        return LiveEvaluation(
            retrieved_count=retrieved_count,
            top_score=top_score,
            score_margin=score_margin,
            duplicate_ratio=duplicate_ratio,
            signals={
                "no_retrieval": no_retrieval,
                "weak_retrieval": weak_retrieval,
                "duplicate_context": duplicate_context,
                "embedding_degraded": embedding_degraded,
                "retrieval_bypassed": retrieval_outcome == "not_required",
                "retrieval_not_attempted": retrieval_outcome == "not_attempted",
                "retrieval_empty": retrieval_outcome == "no_results",
                "evidence_insufficient": evidence_insufficient,
                "generation_failed": generation_failed,
                "infrastructure_failed": infrastructure_failed,
                "retrieval_failed": retrieval_failed,
                "latency_anomaly": latency_anomaly,
            },
            retrieval_outcome=retrieval_outcome,
            latency_anomaly=latency_anomaly,
            slow_stage=slow_stage,
            slow_stage_latency_ms=slow_stage_latency_ms,
            status=status,
        )

    @staticmethod
    def _retrieval_outcome(
        observation: RAGGuardObservation,
    ) -> str:
        if observation.retrieval_required is False:
            return "not_required"
        if observation.retrieval_attempted is False:
            return "not_attempted"
        if observation.retrieved_chunks:
            return "results"
        if observation.retrieval_attempted is True:
            return "no_results"
        if observation.retrieval_required is True:
            return "unknown"
        return "unknown"

    @staticmethod
    def _is_retrieval_failure(
        observation: RAGGuardObservation,
        outcome: str,
    ) -> bool:
        if observation.retrieval_required is False:
            return False
        if observation.retrieval_required is True:
            return not observation.retrieved_chunks
        if observation.retrieval_attempted is not None:
            return observation.retrieval_attempted and not observation.retrieved_chunks
        # Preserve the v1 legacy interpretation when intent telemetry is absent.
        return outcome == "unknown" and not observation.retrieved_chunks

    def _slow_stage(
        self,
        observation: RAGGuardObservation,
    ) -> tuple[bool, str | None, float | None]:
        timings = dict(observation.stage_timings_ms)
        timings.setdefault("retrieval", observation.retrieval_latency_ms)
        for stage, threshold in self.latency_thresholds_ms.items():
            duration = timings.get(stage)
            if duration is not None and duration > threshold:
                return True, stage, duration
        return False, None, None

    @staticmethod
    def _duplicate_ratio(chunks) -> float:
        if not chunks:
            return 0.0

        ids = [chunk.id for chunk in chunks]
        duplicates = len(ids) - len(set(ids))

        return duplicates / len(ids)
