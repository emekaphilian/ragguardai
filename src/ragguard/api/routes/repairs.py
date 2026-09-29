from fastapi import APIRouter, Depends

from ragguard.agents.graph import run_sequential
from ragguard.agents.state import RAGGuardState
from ragguard.api.middleware import tenant_context
from ragguard.api.runtime import workspace
from ragguard.api.schemas import DetectRequest, RepairRequest
from ragguard.auth.tenant_context import TenantContext
from ragguard.config import load_settings
from ragguard.detection.failure_detector import FailureDetector
from ragguard.diagnosis.diagnostic_agent import diagnose
from ragguard.evaluation.evaluator import Evaluator
from ragguard.repair.repair_engine import RepairEngine
from ragguard.common.enums import RepairType
from ragguard.repair.repair_policy import EXECUTABLE_REPAIRS

router = APIRouter()


@router.get("/repair-capabilities")
def repair_capabilities(context: TenantContext = Depends(tenant_context)):
    del context  # The route uses the workspace tenant boundary, not source metadata.
    descriptions = {
        RepairType.DEDUPLICATE: "Remove duplicate chunks from a retrieval candidate.",
        RepairType.HYBRID_RETRIEVAL: "Combine lexical and vector retrieval candidates.",
        RepairType.RERANK: "Reorder retrieved chunks using query relevance.",
    }
    return [
        {
            "strategy": strategy.value,
            "implemented": strategy in EXECUTABLE_REPAIRS,
            "description": descriptions.get(
                strategy,
                "No executable repair strategy is registered for this operation.",
            ),
        }
        for strategy in RepairType
        if strategy != RepairType.HUMAN_ESCALATION
    ]


@router.post("/detect")
def detect(request: DetectRequest, context: TenantContext = Depends(tenant_context)):
    failure = FailureDetector(load_settings().thresholds).detect(request.query, request.metrics)
    return {
        "status": "failure_detected" if failure else "healthy",
        "query": request.query,
        "metrics": request.metrics.model_dump(),
        "failure_detected": failure is not None,
        "failure_type": failure.failure_type.value if failure else None,
        "tenant_id": context.tenant_id,
    }


@router.post("/repair")
def repair(request: RepairRequest, context: TenantContext = Depends(tenant_context)):
    """Run the verified sequential repair path against labeled evidence."""
    settings = load_settings()
    max_repair_attempts = settings.max_repair_attempts
    if request.max_repair_attempts is not None:
        max_repair_attempts = min(
            request.max_repair_attempts,
            settings.max_repair_attempts,
        )
    retrieval = workspace.store.search(
        request.query, top_k=request.top_k, namespace=context.vector_namespace
    )
    evaluator = Evaluator()
    relevant_ids = set(request.relevant_chunk_ids)
    before_metrics = evaluator.evaluate(
        request.query, request.answer, retrieval, relevant_ids
    )
    state = RAGGuardState(
        query=request.query,
        context=context,
        retrieval_result=retrieval,
        evaluation_result=before_metrics,
    )
    state = run_sequential(
        state, FailureDetector(settings.thresholds), diagnose,
        RepairEngine(), workspace.store, evaluator, relevant_ids, request.answer,
        max_repair_attempts=max_repair_attempts,
    )

    result = state.repair_result
    after_metrics = state.evaluation_result or before_metrics
    validation = state.validation_result
    net_improvement = round(
        after_metrics.overall_score - before_metrics.overall_score,
        10,
    )
    repair = {
        "id": f"repair-{len(workspace.repairs) + 1}",
        "query": request.query,
        "status": {
            "repaired": "improved", "rolled_back": "rolled_back",
            "promoted": "improved", "escalated": "escalated",
            "escalate": "escalated", "healthy": "healthy",
        }[state.status],
        "repair_type": result.repair_type.value if result else None,
        "before_metrics": before_metrics.model_dump(),
        "after_metrics": after_metrics.model_dump(),
        "improvement": net_improvement,
        "last_attempt_improvement": result.improvement if result else None,
        "validated": validation.valid if validation else None,
        "attempted_repairs": [repair.value for repair in state.attempted_repairs],
        "max_repair_attempts": max_repair_attempts,
        "completed_nodes": state.completed_nodes,
        "failure_type": state.failure_event.failure_type.value if state.failure_event else None,
        "rollback": state.status == "rolled_back",
        "retrieval": {
            "before": result.before_retrieval_stats if result else {},
            "after": result.after_retrieval_stats if result else {},
        },
        "tenant_id": context.tenant_id,
    }
    workspace.repairs.insert(0, repair)
    return repair


@router.get("/metrics")
def metrics(context: TenantContext = Depends(tenant_context)):
    return workspace.dashboard(context)["metrics"]


@router.get("/failures")
def failures(context: TenantContext = Depends(tenant_context)):
    return [failure for failure in workspace.failures if failure["tenant_id"] == context.tenant_id]


@router.get("/repairs/{repair_id}")
def repair_by_id(repair_id: str, context: TenantContext = Depends(tenant_context)):
    return next((item for item in workspace.repairs if item["id"] == repair_id and item["tenant_id"] == context.tenant_id), {"repair_id": repair_id, "status": "not_found"})
