from fastapi.testclient import TestClient
import pytest
from types import SimpleNamespace

from ragguard.api.app import app
from ragguard.api.routes import observations as observations_route
from ragguard.auth.tenant_context import TenantContext
from ragguard.common.enums import FailureMode
from ragguard.evaluation.live import ObservationSource, RAGObservation
from ragguard.observability.recovery_audit import RecoveryAuditRecord
from ragguard.observability.recovery_repository import InMemoryRecoveryAuditRepository
from ragguard.replay.models import ReplayRequest
from ragguard.replay.comparator import compare_replay
from ragguard.replay.service import (
    RecoveryReplayService,
    ReplayNotFoundError,
    ReplayUnavailableError,
)


def context(tenant_id="development"):
    return TenantContext(
        tenant_id=tenant_id,
        application_id="trustassist",
        environment="development",
        user_id=None,
        roles=(),
        vector_namespace=tenant_id,
        policy_version="v1",
        index_version="v1",
    )


def saved_recovery(repository, *, snapshot=True):
    observation = RAGObservation(
        contract_version="v1",
        source=ObservationSource(
            application_id="trustassist",
            environment="test",
        ),
        query="refund policy",
        retrieved_chunks=[],
        retrieval_method="vector",
    )
    record = RecoveryAuditRecord.create(
        graph_run_id="original-graph",
        failure_id="original-failure",
        failure_type=FailureMode.NO_RETRIEVAL.value,
        application_id="trustassist",
        environment="test",
        tenant_id=None,
        ragguard_tenant_id="development",
        original_score=None,
        observation_snapshot=(
            observation.model_dump(mode="json") if snapshot else None
        ),
    )
    record.final_status = "escalated"
    record.complete("escalated")
    repository.save(record)
    return record


def test_dry_run_replays_saved_observation_without_mutating_original_audit():
    repository = InMemoryRecoveryAuditRepository()
    original = saved_recovery(repository)
    original_event_ids = [event.event_id for event in original.events]
    original_status = original.final_status

    result = RecoveryReplayService(repository).replay(
        ReplayRequest(recovery_id=original.recovery_id),
        context=context(),
    )

    assert result.original_recovery_id == original.recovery_id
    assert result.mode == "dry_run"
    assert result.original_status == original_status
    assert result.replay_status == "escalated"
    assert result.original_strategy is None
    assert result.replay_strategy is None
    assert result.regression_detected is False
    assert repository.get(original.recovery_id) is original
    assert original.final_status == original_status
    assert [event.event_id for event in original.events] == original_event_ids
    assert repository.count(ragguard_tenant_id="development") == 1


def test_replay_hides_records_outside_authenticated_internal_tenant():
    repository = InMemoryRecoveryAuditRepository()
    original = saved_recovery(repository)

    with pytest.raises(ReplayNotFoundError):
        RecoveryReplayService(repository).replay(
            ReplayRequest(recovery_id=original.recovery_id),
            context=context("internal-other"),
        )


def test_replay_requires_a_persisted_observation_snapshot():
    repository = InMemoryRecoveryAuditRepository()
    original = saved_recovery(repository, snapshot=False)

    with pytest.raises(ReplayUnavailableError, match="replayable observation"):
        RecoveryReplayService(repository).replay(
            ReplayRequest(recovery_id=original.recovery_id),
            context=context(),
        )


def test_execute_mode_requires_an_isolated_service_factory():
    repository = InMemoryRecoveryAuditRepository()
    original = saved_recovery(repository)

    with pytest.raises(ReplayUnavailableError, match="isolated repair-service"):
        RecoveryReplayService(repository).replay(
            ReplayRequest(recovery_id=original.recovery_id, mode="execute"),
            context=context(),
        )


def test_execute_mode_rejects_service_without_isolation_marker():
    repository = InMemoryRecoveryAuditRepository()
    original = saved_recovery(repository)

    with pytest.raises(ReplayUnavailableError, match="isolated_replay=True"):
        RecoveryReplayService(
            repository,
            execute_service_factory=lambda _: object(),
        ).replay(
            ReplayRequest(recovery_id=original.recovery_id, mode="execute"),
            context=context(),
        )


def test_comparator_flags_a_score_regression():
    original = RecoveryAuditRecord.create(
        "original-graph",
        failure_type="LOW_CONTEXT_PRECISION",
        original_score=0.6,
    )
    original.final_status = "promoted"
    original.final_score = 0.8
    original.attempts = [{"strategy": "RERANK", "status": "promoted"}]
    replay_state = {
        "status": "promoted",
        "recovery_audit": SimpleNamespace(
            final_score=0.7,
            original_score=0.6,
            attempts=[{"strategy": "DEDUPLICATE", "status": "promoted"}],
        ),
    }

    result = compare_replay(original, replay_state, mode="execute")

    assert result.original_score == 0.8
    assert result.replay_score == 0.7
    assert result.original_strategy == "RERANK"
    assert result.replay_strategy == "DEDUPLICATE"
    assert result.regression_detected is True


def test_replay_http_route_returns_a_dry_run_comparison():
    original = saved_recovery(observations_route.recovery_repository)
    client = TestClient(app)

    response = client.post(
        "/api/v1/replays",
        headers={"X-RAGGuard-Tenant": "development"},
        json={"recovery_id": original.recovery_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["original_recovery_id"] == original.recovery_id
    assert body["mode"] == "dry_run"
    assert body["replay_status"] == "escalated"
    assert "recovery_id" not in body
    assert "candidate_retrieval" not in body


def test_replay_http_route_rejects_execute_without_isolation():
    original = saved_recovery(observations_route.recovery_repository)
    client = TestClient(app)

    response = client.post(
        "/api/v1/replays",
        headers={"X-RAGGuard-Tenant": "development"},
        json={"recovery_id": original.recovery_id, "mode": "execute"},
    )

    assert response.status_code == 409
