from fastapi import APIRouter, Depends
from ragguard.api.schemas import EvaluateRequest
from ragguard.api.runtime import workspace
from ragguard.auth.tenant_context import TenantContext
from ragguard.api.middleware import tenant_context

router = APIRouter()

@router.post("/evaluate")
def evaluate(request: EvaluateRequest, context: TenantContext = Depends(tenant_context)):
    result = workspace.query(request.query, context=context)
    return {"query": request.query, "answer": request.answer, "retrieval_quality": result["retrieval_quality"], "sources": result["sources"], "ground_truth_supplied": bool(request.relevant_chunk_ids)}
