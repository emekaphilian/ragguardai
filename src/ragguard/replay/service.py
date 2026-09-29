from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from ragguard.api.recovery_service import ObservationRecoveryService
from ragguard.auth.tenant_context import TenantContext
from ragguard.diagnosis.diagnostic_agent import diagnose
from ragguard.detection.live_detector import LiveFailureDetector
from ragguard.evaluation.live import RAGObservation
from ragguard.observability.recovery_repository import InMemoryRecoveryAuditRepository
from ragguard.replay.comparator import compare_replay
from ragguard.replay.models import ReplayRequest, ReplayResult
from ragguard.replay.runner import run_replay


class ReplayNotFoundError(LookupError):
    """Raised when an audit record is missing or outside the caller's scope."""


class ReplayUnavailableError(RuntimeError):
    """Raised when the original observation cannot safely be replayed."""


class RecoveryReplayService:
    """Replay saved observations through an isolated recovery-service factory."""

    def __init__(
        self,
        repository,
        *,
        execute_service_factory: Callable | None = None,
    ) -> None:
        self.repository = repository
        self.execute_service_factory = execute_service_factory

    def replay(
        self,
        request: ReplayRequest,
        *,
        context: TenantContext,
    ) -> ReplayResult:
        original = self.repository.get(request.recovery_id)
        if (
            original is None
            or original.ragguard_tenant_id != context.tenant_id
            or original.application_id != context.application_id
        ):
            raise ReplayNotFoundError("Recovery record not found.")

        if not original.observation_snapshot:
            raise ReplayUnavailableError(
                "This recovery record does not contain a replayable observation."
            )

        if request.mode == "execute":
            if self.execute_service_factory is None:
                raise ReplayUnavailableError(
                    "Execute replay requires an isolated repair-service factory."
                )
            recovery_service = self.execute_service_factory(original)
            if not getattr(recovery_service, "isolated_replay", False):
                raise ReplayUnavailableError(
                    "Execute replay service must declare isolated_replay=True."
                )
        else:
            recovery_service = ObservationRecoveryService(
                detector=LiveFailureDetector(),
                diagnosis_fn=diagnose,
                recovery_repository=InMemoryRecoveryAuditRepository(),
                available_repairs=(),
                max_repair_attempts=0,
            )

        observation = RAGObservation.model_validate(original.observation_snapshot)
        replay_state = run_replay(
            observation=observation,
            context=context,
            recovery_service=recovery_service,
        )
        replay_state.setdefault("recovery_id", str(uuid4()))
        return compare_replay(original, replay_state, mode=request.mode)
