from fastapi import APIRouter, Depends
from ragguard.api.runtime import workspace
from ragguard.auth.tenant_context import TenantContext
from ragguard.api.middleware import tenant_context
router = APIRouter()

@router.get('/dashboard')
def dashboard(context: TenantContext = Depends(tenant_context)):
    return workspace.dashboard(context)

@router.get('/runs')
def runs(context: TenantContext = Depends(tenant_context)): return [run for run in workspace.runs if run["tenant_id"] == context.tenant_id]
