from dataclasses import replace

from fastapi import APIRouter, Header, HTTPException

from ragguard.auth.service_auth import (
    ServiceAuthenticationError,
    authenticate_service,
)
from ragguard.api.observation_recovery import build_recovery_response
from ragguard.api.recovery_service import ObservationRecoveryService
from ragguard.api.schemas import ObservationRecoveryResponse
from ragguard.config import load_settings
from ragguard.diagnosis.diagnostic_agent import diagnose
from ragguard.detection.live_detector import LiveFailureDetector
from ragguard.evaluation.live import RAGObservation
from ragguard.evaluation.live_evaluator import LiveEvaluator
from ragguard.observability.observation_activity import ObservationRecord
from ragguard.persistence.repositories import create_recovery_audit_repository
from ragguard.api.runtime import observation_repository
from ragguard.events.bus import InMemoryRecoveryEventBus

router = APIRouter()

evaluator = LiveEvaluator()
detector = LiveFailureDetector()
recovery_repository = create_recovery_audit_repository()
recovery_event_bus = InMemoryRecoveryEventBus(
    event_retention_days=load_settings().event_retention_days,
)
recovery_service = ObservationRecoveryService(
    detector=detector,
    diagnosis_fn=diagnose,
    recovery_repository=recovery_repository,
    event_bus=recovery_event_bus,
)


@router.post("/observations", response_model=ObservationRecoveryResponse)
def observe(
    observation: RAGObservation,
    authorization: str | None = Header(default=None),
):
    """Evaluate a generic RAG observation supplied by any application adapter."""
    try:
        authenticated_service = authenticate_service(
            authorization,
            load_settings(),
        )
    except ServiceAuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    if observation.source.application_id != authenticated_service.application_id:
        raise HTTPException(
            status_code=403,
            detail="Observation source does not match the authenticated service.",
        )

    evaluation = evaluator.evaluate(observation)
    failure = detector.detect(observation, evaluation)
    observation_record = ObservationRecord.create(
        ragguard_tenant_id=authenticated_service.tenant_context.tenant_id,
        application_id=authenticated_service.application_id,
        status="healthy" if failure is None else "failure",
        query=observation.query,
        evaluation=evaluation.model_dump(mode="json"),
        observation=observation.model_dump(
            mode="json",
            exclude={"embedding_fallback", "embedding_failure"},
        ),
        failure=failure.model_dump(mode="json") if failure is not None else None,
        recovery=None,
    )
    observation_repository.save(observation_record)

    if failure is None:
        return ObservationRecoveryResponse(
            status="healthy",
            evaluation=evaluation,
            failure=None,
            recovery=None,
        )

    state = recovery_service.recover(
        observation=observation,
        context=authenticated_service.tenant_context,
        evaluation=evaluation,
        failure_event=failure,
    )
    recovery = build_recovery_response(state)

    response = ObservationRecoveryResponse(
        status=recovery["status"],
        evaluation=evaluation,
        failure=failure,
        recovery=recovery,
    )
    observation_repository.save(replace(
        observation_record,
        status=response.status,
        recovery=(
            response.recovery.model_dump(mode="json")
            if response.recovery is not None
            else None
        ),
    ))
    return response
