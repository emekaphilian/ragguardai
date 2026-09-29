from __future__ import annotations

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
    ):
        self.weak_top_score = weak_top_score
        self.ambiguous_margin = ambiguous_margin
        self.duplicate_ratio = duplicate_ratio

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

        no_retrieval = retrieved_count == 0
        weak_retrieval = (
            top_score is not None
            and top_score < self.weak_top_score
        )
        duplicate_context = duplicate_ratio >= self.duplicate_ratio
        embedding_degraded = (
            observation.embedding_degraded
            or observation.embedding_fallback
            or observation.embedding_failure
        )

        if no_retrieval:
            status = "FAILURE"
        elif weak_retrieval or duplicate_context or embedding_degraded:
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
            },
            status=status,
        )

    @staticmethod
    def _duplicate_ratio(chunks) -> float:
        if not chunks:
            return 0.0

        ids = [chunk.id for chunk in chunks]
        duplicates = len(ids) - len(set(ids))

        return duplicates / len(ids)
