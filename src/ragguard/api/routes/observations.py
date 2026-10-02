from dataclasses import replace

from fastapi import APIRouter, Header, HTTPException

from ragguard.auth.service_auth import (
    ServiceAuthenticationError,
    authenticate_service,
)
from ragguard.api.observation_recovery import build_recovery_response
from ragguard.api.recovery_service import ObservationRecoveryService
from ragguard.api.schemas import ObservationRecoveryResponse, RecoveryResultResponse
from ragguard.config import load_settings
from ragguard.diagnosis.diagnostic_agent import diagnose
from ragguard.detection.live_detector import LiveFailureDetector
from ragguard.evaluation.live import RAGObservation
from ragguard.evaluation.live_evaluator import LiveEvaluator
from ragguard.observability.observation_activity import ObservationRecord
from ragguard.persistence.repositories import create_recovery_audit_repository
from ragguard.api.runtime import application_repository, observation_repository
from ragguard.events.bus import InMemoryRecoveryEventBus
from ragguard.observability.recovery_audit import RecoveryAuditRecord, RecoveryEventType
from ragguard.repair.repair_policy import EXECUTABLE_REPAIRS

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
            application_id=observation.source.application_id,
            environment=observation.source.environment,
            application_repository=application_repository,
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

    registration = authenticated_service.registration or application_repository.get(
        authenticated_service.tenant_context.tenant_id,
        authenticated_service.application_id,
        observation.source.environment,
    )
    repair_capability = "available" if EXECUTABLE_REPAIRS else "unavailable"
    if registration is None or not registration.repair_authorized:
        authorization_source = (
            "application_registration"
            if registration is not None
            else "missing_application_registration"
        )
        authorization_reason = (
            "RAGGuard detected the failure but did not perform a repair because "
            "the application has not authorized RAGGuard to modify its retrieval system."
            if registration is not None
            else "RAGGuard detected the failure but did not perform a repair because "
            "no active application registration grants repair authorization."
        )
        recovery_record = RecoveryAuditRecord.create(
            graph_run_id=None,
            failure_id=failure.failure_id,
            failure_type=failure.failure_type.value,
            application_id=authenticated_service.application_id,
            environment=observation.source.environment,
            ragguard_tenant_id=authenticated_service.tenant_context.tenant_id,
            observation_snapshot=observation.model_dump(mode="json"),
            repair_capability=repair_capability,
            repair_authorization="not_authorized",
            repair_attempted=False,
            authorization_source=authorization_source,
            authorization_reason=authorization_reason,
        )
        recovery_record.add_event(
            RecoveryEventType.REPAIR_NOT_AUTHORIZED,
            status="not_authorized",
            reason=authorization_reason,
            metadata={
                "repair_capability": repair_capability,
                "repair_authorization": "not_authorized",
                "repair_attempted": False,
                "authorization_source": authorization_source,
            },
        )
        recovery_record.complete("repair_not_authorized")
        recovery_repository.save(recovery_record)

        recovery = RecoveryResultResponse(
            status="repair_not_authorized",
            recovery_id=recovery_record.recovery_id,
            graph_run_id=None,
            failure_detected=True,
            failure_type=failure.failure_type.value,
            repair_capability=repair_capability,
            repair_authorization="not_authorized",
            repair_attempted=False,
            authorization_source=authorization_source,
            authorization_reason=authorization_reason,
        )
        response = ObservationRecoveryResponse(
            status="repair_not_authorized",
            evaluation=evaluation,
            failure=failure,
            recovery=recovery,
        )
        observation_repository.save(replace(
            observation_record,
            status=response.status,
            recovery=recovery.model_dump(mode="json"),
        ))
        return response

    state = recovery_service.recover(
        observation=observation,
        context=authenticated_service.tenant_context,
        evaluation=evaluation,
        failure_event=failure,
    )
    recovery = build_recovery_response(state)
    recovery["repair_capability"] = repair_capability
    recovery["repair_authorization"] = "authorized"
    recovery["repair_attempted"] = bool(recovery.get("attempts"))
    recovery["authorization_source"] = "application_registration"
    recovery["authorization_reason"] = None
    recovery_record = recovery_repository.get(recovery["recovery_id"])
    if recovery_record is not None:
        recovery_record.repair_capability = repair_capability
        recovery_record.repair_authorization = "authorized"
        recovery_record.repair_attempted = bool(recovery.get("attempts"))
        recovery_record.authorization_source = "application_registration"
        recovery_repository.save(recovery_record)

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
