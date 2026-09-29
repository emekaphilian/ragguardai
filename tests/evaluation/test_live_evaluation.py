from ragguard.common.enums import FailureMode
from ragguard.detection.live_detector import LiveFailureDetector
from ragguard.evaluation.live_evaluator import LiveEvaluator
from ragguard.evaluation.live import (
    RAGGuardObservation,
    ObservationSource,
    RetrievedChunkObservation,
)


def observation(
    chunks,
    method="hybrid",
    fallback=False,
    failure=False,
):
    return RAGGuardObservation(
        contract_version="v1",
        source=ObservationSource(
            application_id="test-app",
            environment="test",
        ),
        query="What payment methods are supported?",
        retrieved_chunks=chunks,
        retrieval_count=len(chunks),
        retrieval_method=method,
        embedding_fallback=fallback,
        embedding_failure=failure,
        retrieval_latency_ms=25.0,
        trusted=True,
    )


def test_healthy_retrieval():
    obs = observation([
        RetrievedChunkObservation(id="a", score=0.86),
        RetrievedChunkObservation(id="b", score=0.79),
        RetrievedChunkObservation(id="c", score=0.54),
    ])

    result = LiveEvaluator().evaluate(obs)

    assert result.status == "HEALTHY"
    assert result.retrieved_count == 3
    assert result.top_score == 0.86
    assert result.duplicate_ratio == 0.0
    assert not result.signals["no_retrieval"]
    assert not result.signals["weak_retrieval"]


def test_no_retrieval():
    obs = observation([])

    result = LiveEvaluator().evaluate(obs)
    failure = LiveFailureDetector().detect(obs, result)

    assert result.status == "FAILURE"
    assert result.signals["no_retrieval"]
    assert failure is not None
    assert failure.failure_type == FailureMode.NO_RETRIEVAL


def test_duplicate_context_below_threshold():
    obs = observation([
        RetrievedChunkObservation(id="a", score=0.86),
        RetrievedChunkObservation(id="a", score=0.82),
        RetrievedChunkObservation(id="b", score=0.75),
        RetrievedChunkObservation(id="b", score=0.70),
        RetrievedChunkObservation(id="c", score=0.60),
    ])

    result = LiveEvaluator().evaluate(obs)
    failure = LiveFailureDetector().detect(obs, result)

    assert result.status == "HEALTHY"
    assert result.duplicate_ratio == 0.4
    assert result.signals["duplicate_context"] is False
    assert failure is None


def test_duplicate_context_at_threshold():
    obs = observation([
        RetrievedChunkObservation(id="a", score=0.86),
        RetrievedChunkObservation(id="a", score=0.82),
        RetrievedChunkObservation(id="a", score=0.80),
        RetrievedChunkObservation(id="b", score=0.70),
    ])

    result = LiveEvaluator().evaluate(obs)
    failure = LiveFailureDetector().detect(obs, result)

    assert result.status == "DEGRADED"
    assert result.duplicate_ratio == 0.5
    assert result.signals["duplicate_context"]
    assert failure is not None
    assert failure.failure_type == FailureMode.DUPLICATE_CONTEXT


def test_embedding_fallback():
    obs = observation(
        [
            RetrievedChunkObservation(id="a", score=0.86),
            RetrievedChunkObservation(id="b", score=0.70),
        ],
        method="keyword_fallback",
        fallback=True,
    )

    result = LiveEvaluator().evaluate(obs)
    failure = LiveFailureDetector().detect(obs, result)

    assert result.status == "DEGRADED"
    assert result.signals["embedding_degraded"]
    assert failure is not None
    assert failure.failure_type == FailureMode.EMBEDDING_DEGRADED


def test_weak_retrieval():
    obs = observation([
        RetrievedChunkObservation(id="a", score=0.29),
        RetrievedChunkObservation(id="b", score=0.21),
    ])

    result = LiveEvaluator().evaluate(obs)
    failure = LiveFailureDetector().detect(obs, result)

    assert result.status == "DEGRADED"
    assert result.signals["weak_retrieval"]
    assert failure is not None
    assert failure.failure_type == FailureMode.WEAK_RETRIEVAL
