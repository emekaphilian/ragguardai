import pytest
from pydantic import ValidationError

from ragguard.common.enums import FailureMode
from ragguard.config import load_settings
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
        retrieval_method=method,
        embedding_fallback=fallback,
        embedding_failure=failure,
        retrieval_latency_ms=25.0,
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


def test_intentional_retrieval_bypass_is_not_a_failure():
    obs = observation([])
    obs.retrieval_required = False
    obs.retrieval_attempted = False

    result = LiveEvaluator().evaluate(obs)

    assert result.status == "HEALTHY"
    assert result.retrieval_outcome == "not_required"
    assert result.signals["retrieval_bypassed"]
    assert not result.signals["no_retrieval"]
    assert LiveFailureDetector().detect(obs, result) is None


def test_required_retrieval_not_attempted_is_a_failure():
    obs = observation([])
    obs.retrieval_required = True
    obs.retrieval_attempted = False

    result = LiveEvaluator().evaluate(obs)
    failure = LiveFailureDetector().detect(obs, result)

    assert result.status == "FAILURE"
    assert result.retrieval_outcome == "not_attempted"
    assert result.signals["retrieval_not_attempted"]
    assert failure is not None
    assert failure.failure_type == FailureMode.NO_RETRIEVAL
    assert "not attempted" in failure.evidence[0]


def test_attempted_retrieval_without_results_is_a_failure():
    obs = observation([])
    obs.retrieval_required = True
    obs.retrieval_attempted = True

    result = LiveEvaluator().evaluate(obs)
    failure = LiveFailureDetector().detect(obs, result)

    assert result.retrieval_outcome == "no_results"
    assert result.signals["retrieval_empty"]
    assert failure is not None
    assert failure.failure_type == FailureMode.NO_RETRIEVAL
    assert "returned no chunks" in failure.evidence[0]


def test_retrieval_results_do_not_report_no_retrieval():
    obs = observation([RetrievedChunkObservation(id="a", score=0.8)])
    obs.retrieval_required = True
    obs.retrieval_attempted = True

    result = LiveEvaluator().evaluate(obs)

    assert result.retrieval_outcome == "results"
    assert not result.signals["no_retrieval"]


def test_explicit_generation_and_infrastructure_failures_are_distinguished():
    obs = observation([RetrievedChunkObservation(id="a", score=0.8)])
    obs.generation_status = "failed"
    result = LiveEvaluator().evaluate(obs)
    failure = LiveFailureDetector().detect(obs, result)
    assert failure is not None
    assert failure.failure_type == FailureMode.GENERATION_FAILURE

    obs.generation_status = None
    obs.failed_stage = "external_service"
    obs.error_code = "UPSTREAM_TIMEOUT"
    result = LiveEvaluator().evaluate(obs)
    failure = LiveFailureDetector().detect(obs, result)
    assert failure is not None
    assert failure.failure_type == FailureMode.INFRASTRUCTURE_FAILURE


def test_latency_diagnosis_uses_explicit_thresholds_and_stage_evidence():
    obs = observation([RetrievedChunkObservation(id="a", score=0.8)])
    obs.retrieval_latency_ms = 25.0
    obs.stage_timings_ms = {"generation": 900.0}

    unconfigured = LiveEvaluator().evaluate(obs)
    assert not unconfigured.signals["latency_anomaly"]

    evaluator = LiveEvaluator(latency_thresholds_ms={"generation": 500.0})
    result = evaluator.evaluate(obs)
    failure = LiveFailureDetector().detect(obs, result)

    assert result.slow_stage == "generation"
    assert result.slow_stage_latency_ms == 900.0
    assert failure is not None
    assert failure.failure_type == FailureMode.LATENCY_ANOMALY
    assert "generation latency=900.0ms" in failure.evidence[0]


def test_observation_rejects_invalid_stage_timings_and_contract_versions():
    with pytest.raises(ValidationError):
        RAGGuardObservation(
            contract_version="v1",
            source=ObservationSource(application_id="test-app", environment="test"),
            query="question",
            stage_timings_ms={"retrieval": -1},
        )
    with pytest.raises(ValidationError):
        RAGGuardObservation(
            contract_version="v2",
            source=ObservationSource(application_id="test-app", environment="test"),
            query="question",
        )
    with pytest.raises(ValidationError):
        RAGGuardObservation(
            contract_version="v1",
            source=ObservationSource(
                application_id="test-app",
                environment="test",
                tenant_id="internal-tenant",
            ),
            query="question",
        )
    with pytest.raises(ValidationError):
        RAGGuardObservation(
            contract_version="v1",
            source=ObservationSource(application_id="test-app", environment="test"),
            query="",
            unrecognized_field=True,
        )


def test_stage_latency_thresholds_load_from_configuration(tmp_path):
    config = tmp_path / "latency-config.yaml"
    config.write_text(
        "live_latency_thresholds_ms:\n"
        "  retrieval: 250\n"
        "  generation: 1200\n",
        encoding="utf-8",
    )

    settings = load_settings(str(config))

    assert settings.live_latency_thresholds_ms == {
        "retrieval": 250.0,
        "generation": 1200.0,
    }


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
