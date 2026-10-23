from dataclasses import replace

from fastapi import APIRouter, Header, HTTPException

from ragguard.auth.service_auth import (
    ServiceAuthenticationError,
    authenticate_service,
)
from ragguard.api.observation_recovery import build_recovery_response
from ragguard.api.recovery_service import ObservationRecoveryService
from ragguard.api.external_repair import (
    get_supported_repairs,
    request_external_repair,
)
from ragguard.api.schemas import (
    ObservationRecoveryResponse,
    RecoveryAttemptResponse,
    RecoveryResultResponse,
)
from ragguard.config import load_settings
from ragguard.diagnosis.diagnostic_agent import diagnose
from ragguard.detection.live_detector import LiveFailureDetector
from ragguard.evaluation.live import RAGObservation
from ragguard.evaluation.live_evaluator import LiveEvaluator
from ragguard.observability.observation_activity import ObservationRecord
from ragguard.persistence.repositories import create_recovery_audit_repository
from ragguard.api.runtime import application_repository, observation_repository
from ragguard.common.capabilities import capability_execution, capability_state
from ragguard.events.bus import InMemoryRecoveryEventBus
from ragguard.observability.recovery_audit import RecoveryAuditRecord, RecoveryEventType
from ragguard.repair.repair_policy import (
    EXECUTABLE_REPAIRS,
    choose_executable_repair,
)

router = APIRouter()

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


def _set_capability_execution(recovery_record, states):
    recovery_record.capability_execution = states


def _recover_external_application(
    *,
    observation: RAGObservation,
    observation_record,
    authenticated_service,
    evaluation,
    failure,
    registration,
    supported_repairs,
):
    diagnosis = recovery_service.diagnosis_fn(failure)
    strategy = choose_executable_repair(
        diagnosis,
        available=supported_repairs,
    )
    capabilities = capability_execution(
        context_verification=capability_state(
            "not_applicable",
            performed=False,
            reason="external_application_retains_context",
        ),
        independent_verification=capability_state(
            "not_applicable",
            performed=False,
            reason="external_application_operation",
        ),
        repair=capability_state(
            "authorized",
            performed=False,
            reason="no_supported_repair_recommended",
        ),
    )
    audit = RecoveryAuditRecord.create(
        graph_run_id=None,
        failure_id=failure.failure_id,
        failure_type=failure.failure_type.value,
        application_id=registration.application_id,
        environment=registration.environment,
        ragguard_tenant_id=authenticated_service.tenant_context.tenant_id,
        observation_snapshot=observation.model_dump(mode="json"),
        repair_capability="available" if supported_repairs else "unavailable",
        repair_authorization="authorized",
        authorization_source="application_registration",
        capability_execution=capabilities,
    )
    audit.add_event(
        RecoveryEventType.DIAGNOSIS_COMPLETED,
        status="diagnosed",
        reason=diagnosis.root_cause.value,
        metadata={
            "confidence": diagnosis.confidence,
            "evidence": diagnosis.evidence,
            "recommended_repairs": [
                item.value for item in diagnosis.recommended_repairs
            ],
        },
    )

    attempts = []
    validated = None
    improvement = None
    attempted = False
    completed_nodes = ["diagnose"]
    authorization_reason = None
    if strategy is None:
        status = "repair_unavailable"
        authorization_reason = (
            "No supported repair strategy was recommended for this observation."
        )
        audit.add_event(
            RecoveryEventType.REPAIR_PLANNED,
            status="unavailable",
            reason=authorization_reason,
            metadata={"supported_repairs": [item.value for item in supported_repairs]},
        )
    else:
        audit.add_event(
            RecoveryEventType.REPAIR_PLANNED,
            attempt=1,
            strategy=strategy.value,
            status="planned",
        )
        audit.add_event(
            RecoveryEventType.REPAIR_STARTED,
            attempt=1,
            strategy=strategy.value,
            status="started",
        )
        attempted = True
        completed_nodes.append("repair")
        try:
            result = request_external_repair(
                registration,
                observation,
                failure_type=failure.failure_type.value,
                strategy=strategy,
            )
        except Exception:
            status = "repair_unavailable"
            authorization_reason = (
                "The external repair adapter did not complete the requested operation."
            )
            attempts.append(RecoveryAttemptResponse(
                strategy=strategy.value,
                status="failed",
            ))
            audit.attempts.append({
                "attempt": 1,
                "strategy": strategy.value,
                "status": "failed",
                "improvement": None,
                "validation_valid": None,
            })
            audit.add_event(
                RecoveryEventType.REPAIR_COMPLETED,
                attempt=1,
                strategy=strategy.value,
                status="failed",
                reason="external_repair_adapter_failed",
            )
        else:
            validated = result.validated
            improvement = result.improvement
            attempts.append(RecoveryAttemptResponse(
                strategy=strategy.value,
                status=result.status,
                improvement=result.improvement,
            ))
            completed_nodes.append("validate")
            capabilities["repair"] = capability_state(
                "authorized",
                performed=True,
            )
            audit.add_event(
                RecoveryEventType.REPAIR_COMPLETED,
                attempt=1,
                strategy=strategy.value,
                status=result.status,
                improvement=result.improvement,
            )
            audit.attempts.append({
                "attempt": 1,
                "strategy": strategy.value,
                "status": result.status,
                "improvement": result.improvement,
                "validation_valid": result.validated,
                "context_verified": result.context_verified,
            })
            audit.add_event(
                RecoveryEventType.VALIDATION_COMPLETED,
                attempt=1,
                strategy=strategy.value,
                status="validated" if result.validated else "rejected",
                improvement=result.improvement,
                validation_valid=result.validated,
                validation_improved=(
                    result.improvement > 0
                    if result.improvement is not None
                    else None
                ),
                metadata={"context_verified": result.context_verified},
            )
            if result.status == "promoted":
                status = "promoted"
            else:
                status = "escalated"
                audit.add_event(
                    RecoveryEventType.ROLLBACK,
                    attempt=1,
                    strategy=strategy.value,
                    status=result.status,
                    improvement=result.improvement,
                )

    capabilities["repair"] = capability_state(
        "authorized",
        performed=attempted,
        reason=(
            "external_repair_adapter_failed"
            if attempted and validated is None
            else "no_supported_repair_recommended"
            if not attempted
            else None
        ),
    )
    _set_capability_execution(audit, capabilities)
    audit.repair_attempted = attempted
    audit.authorization_reason = authorization_reason
    audit.complete(
        status,
        improvement=improvement,
    )
    recovery_repository.save(audit)

    recovery = RecoveryResultResponse(
        status=status,
        recovery_id=audit.recovery_id,
        failure_detected=True,
        failure_type=failure.failure_type.value,
        diagnosis=diagnosis,
        attempts=attempts,
        improvement=improvement,
        completed_nodes=completed_nodes,
        repair_capability="available" if supported_repairs else "unavailable",
        repair_supported=bool(supported_repairs),
        repair_eligible=strategy is not None,
        repair_validated=validated,
        repair_authorization="authorized",
        repair_attempted=attempted,
        authorization_source="application_registration",
        authorization_reason=authorization_reason,
        capability_execution=capabilities,
    )
    response = ObservationRecoveryResponse(
        status=status,
        evaluation=evaluation,
        failure=failure,
        recovery=recovery,
        capability_execution=capabilities,
    )
    observation_repository.save(replace(
        observation_record,
        status=response.status,
        recovery=recovery.model_dump(mode="json"),
        capability_execution=capabilities,
    ))
    return response


@router.post("/observations", response_model=ObservationRecoveryResponse)
def observe(
    observation: RAGObservation,
    authorization: str | None = Header(default=None),
):
    """Evaluate a generic RAG observation supplied by any application adapter."""
    settings = load_settings()
    try:
        authenticated_service = authenticate_service(
            authorization,
            settings,
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

    registration = authenticated_service.registration or application_repository.get(
        authenticated_service.tenant_context.tenant_id,
        authenticated_service.application_id,
        observation.source.environment,
    )
    context_authorized = bool(
        registration and registration.context_verification_authorized
    )
    independent_authorized = bool(
        registration and registration.independent_verification_authorized
    )
    repair_authorized = bool(registration and registration.repair_authorized)
    initial_capabilities = capability_execution(
        context_verification=(
            capability_state(
                "authorized",
                performed=False,
                reason="context_not_supplied",
            )
            if context_authorized
            else capability_state(
                "not_authorized",
                performed=False,
                reason=(
                    "application_not_authorized"
                    if registration
                    else "application_not_registered"
                ),
            )
        ),
        independent_verification=(
            capability_state(
                "not_applicable",
                performed=False,
                reason="managed_index",
            )
            if registration and registration.knowledge_source == "managed_index"
            else capability_state(
                "not_applicable",
                performed=False,
                reason="observation_only_operation",
            )
            if registration and registration.knowledge_source == "observation_only"
            else capability_state(
                "authorized",
                performed=False,
                reason="not_requested_by_observation",
            )
            if independent_authorized
            else capability_state(
                "not_authorized",
                performed=False,
                reason=(
                    "application_not_authorized"
                    if registration
                    else "application_not_registered"
                ),
            )
        ),
        repair=(
            capability_state(
                "authorized",
                performed=False,
                reason="no_failure_detected",
            )
            if repair_authorized
            else capability_state(
                "not_authorized",
                performed=False,
                reason=(
                    "application_not_authorized"
                    if registration
                    else "application_not_registered"
                ),
            )
        ),
    )

    evaluation = LiveEvaluator(
        latency_thresholds_ms=settings.live_latency_thresholds_ms,
    ).evaluate(observation)
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
        capability_execution=initial_capabilities,
    )
    observation_repository.save(observation_record)

    if failure is None:
        return ObservationRecoveryResponse(
            status="healthy",
            evaluation=evaluation,
            failure=None,
            recovery=None,
            capability_execution=initial_capabilities,
        )

    remote_repairs = frozenset()
    if (
        registration
        and registration.knowledge_source in {"external_rag_api", "observation_only"}
        and repair_authorized
        and registration.repair_endpoint_url
        and registration.repair_token_env_var
    ):
        try:
            remote_repairs = get_supported_repairs(registration)
        except Exception:
            remote_repairs = frozenset()
    repair_supported = bool(
        registration
        and (
            registration.knowledge_source == "managed_index"
            or remote_repairs
        )
    )
    repair_capability = "available" if EXECUTABLE_REPAIRS else "unavailable"
    denial_reason = None
    if not repair_authorized:
        denial_reason = (
            "RAGGuard detected the failure but did not perform a repair because "
            "the application has not authorized RAGGuard to modify its retrieval system."
            if registration is not None
            else "RAGGuard detected the failure but did not perform a repair because "
            "no active application registration grants repair authorization."
        )
    elif (
        registration.knowledge_source == "managed_index"
        and not context_authorized
    ):
        denial_reason = (
            "RAGGuard detected the failure but cannot validate a repair because "
            "the application has not authorized context verification."
        )
    elif not repair_supported:
        denial_reason = (
            "RAGGuard detected the failure but no repair adapter supports this "
            "application's knowledge source."
        )

    if denial_reason is not None:
        diagnosis = recovery_service.diagnosis_fn(failure)
        repair_eligible = False
        operation_authorized = repair_authorized
        outcome_status = (
            "repair_not_authorized"
            if not repair_authorized
            or (
                registration.knowledge_source == "managed_index"
                and not context_authorized
            )
            else "repair_unavailable"
        )
        authorization_source = (
            "application_registration"
            if registration is not None
            else "missing_application_registration"
        )
        denial_capabilities = capability_execution(
            context_verification=initial_capabilities["context_verification"],
            independent_verification=initial_capabilities[
                "independent_verification"
            ],
            repair=(
                initial_capabilities["repair"]
                if not repair_authorized
                else capability_state(
                    "authorized",
                    performed=False,
                    reason=(
                        "context_verification_not_authorized"
                        if (
                            registration.knowledge_source == "managed_index"
                            and not context_authorized
                        )
                        else "repair_adapter_unavailable"
                    ),
                )
            ),
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
            repair_authorization=(
                "authorized" if operation_authorized else "not_authorized"
            ),
            repair_attempted=False,
            authorization_source=authorization_source,
            authorization_reason=denial_reason,
            capability_execution=denial_capabilities,
        )
        _set_capability_execution(recovery_record, denial_capabilities)
        recovery_record.add_event(
            RecoveryEventType.DIAGNOSIS_COMPLETED,
            status="diagnosed",
            reason=diagnosis.root_cause.value,
            metadata={
                "confidence": diagnosis.confidence,
                "evidence": diagnosis.evidence,
                "recommended_repairs": [
                    item.value for item in diagnosis.recommended_repairs
                ],
            },
        )
        recovery_record.add_event(
            (
                RecoveryEventType.REPAIR_NOT_AUTHORIZED
                if outcome_status == "repair_not_authorized"
                else RecoveryEventType.REPAIR_PLANNED
            ),
            status=(
                "not_authorized"
                if outcome_status == "repair_not_authorized"
                else "unavailable"
            ),
            reason=denial_reason,
            metadata={
                "repair_capability": repair_capability,
                "repair_supported": repair_supported,
                "repair_eligible": repair_eligible,
                "repair_authorization": (
                    "authorized" if operation_authorized else "not_authorized"
                ),
                "repair_attempted": False,
                "repair_validated": None,
                "authorization_source": authorization_source,
            },
        )
        recovery_record.complete(outcome_status)
        recovery_repository.save(recovery_record)

        recovery = RecoveryResultResponse(
            status=outcome_status,
            recovery_id=recovery_record.recovery_id,
            graph_run_id=None,
            failure_detected=True,
            failure_type=failure.failure_type.value,
            diagnosis=diagnosis,
            repair_capability=repair_capability,
            repair_supported=repair_supported,
            repair_eligible=repair_eligible,
            repair_validated=None,
            repair_authorization=(
                "authorized" if operation_authorized else "not_authorized"
            ),
            repair_attempted=False,
            authorization_source=authorization_source,
            authorization_reason=denial_reason,
            capability_execution=denial_capabilities,
        )
        response = ObservationRecoveryResponse(
            status=outcome_status,
            evaluation=evaluation,
            failure=failure,
            recovery=recovery,
            capability_execution=denial_capabilities,
        )
        observation_repository.save(replace(
            observation_record,
            status=response.status,
            recovery=recovery.model_dump(mode="json"),
            capability_execution=denial_capabilities,
        ))
        return response

    if (
        registration
        and registration.knowledge_source in {"external_rag_api", "observation_only"}
        and remote_repairs
    ):
        return _recover_external_application(
            observation=observation,
            observation_record=observation_record,
            authenticated_service=authenticated_service,
            evaluation=evaluation,
            failure=failure,
            registration=registration,
            supported_repairs=remote_repairs,
        )

    state = recovery_service.recover(
        observation=observation,
        context=authenticated_service.tenant_context,
        evaluation=evaluation,
        failure_event=failure,
    )
    recovery = build_recovery_response(state)
    repair_state = capability_state(
        "authorized",
        performed=bool(recovery.get("attempts")),
        reason=None if recovery.get("attempts") else "no_repair_attempt_recorded",
    )
    capability_results = capability_execution(
        context_verification=initial_capabilities["context_verification"],
        independent_verification=initial_capabilities["independent_verification"],
        repair=repair_state,
    )
    recovery["repair_capability"] = repair_capability
    recovery["repair_supported"] = repair_supported
    recovery["repair_eligible"] = bool(
        recovery_service.available_repairs
        and repair_authorized
        and recovery.get("diagnosis")
        and any(
            repair in recovery_service.available_repairs
            for repair in recovery["diagnosis"].recommended_repairs
        )
    )
    recovery["repair_authorization"] = "authorized"
    recovery["repair_attempted"] = bool(recovery.get("attempts"))
    recovery["repair_validated"] = (
        any(attempt.get("status") == "promoted" for attempt in recovery["attempts"])
        if recovery.get("attempts")
        else None
    )
    recovery["authorization_source"] = "application_registration"
    recovery["authorization_reason"] = None
    recovery["capability_execution"] = capability_results
    recovery_record = recovery_repository.get(recovery["recovery_id"])
    if recovery_record is not None:
        recovery_record.repair_capability = repair_capability
        recovery_record.repair_authorization = "authorized"
        recovery_record.repair_attempted = bool(recovery.get("attempts"))
        recovery_record.authorization_source = "application_registration"
        planned_event = next(
            (
                event for event in reversed(recovery_record.events)
                if event.event_type == RecoveryEventType.REPAIR_PLANNED
            ),
            None,
        )
        if planned_event is not None:
            planned_event.metadata.update({
                "repair_capability": repair_capability,
                "repair_supported": repair_supported,
                "repair_eligible": recovery["repair_eligible"],
                "repair_authorization": "authorized",
                "repair_attempted": recovery["repair_attempted"],
                "repair_validated": recovery["repair_validated"],
            })
        _set_capability_execution(recovery_record, capability_results)
        recovery_repository.save(recovery_record)

    response = ObservationRecoveryResponse(
        status=recovery["status"],
        evaluation=evaluation,
        failure=failure,
        recovery=recovery,
        capability_execution=capability_results,
    )
    observation_repository.save(replace(
        observation_record,
        status=response.status,
        recovery=(
            response.recovery.model_dump(mode="json")
            if response.recovery is not None
            else None
        ),
        capability_execution=capability_results,
    ))
    return response
