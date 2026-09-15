from fastapi import APIRouter, Depends
from ragguard.api.schemas import DetectRequest, RepairRequest
from ragguard.api.runtime import workspace
from ragguard.auth.tenant_context import TenantContext
from ragguard.api.middleware import tenant_context

router = APIRouter()

@router.post("/detect")
def detect(request: DetectRequest, context: TenantContext = Depends(tenant_context)):
    return {"status": "recorded", "query": request.query, "metrics": request.metrics}

@router.post("/repair")
def repair(request: RepairRequest, context: TenantContext = Depends(tenant_context)):
    result = workspace.query(request.query, method="hybrid", context=context)
    repair = {"id": f"repair-{len(workspace.repairs) + 1}", "repair_type": request.repair_type, "query": request.query, "status": "completed", "result": result, "tenant_id": context.tenant_id}
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
