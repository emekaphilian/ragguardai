from fastapi import APIRouter, Depends

from ragguard.api.middleware import tenant_context
from ragguard.api.runtime import application_repository
from ragguard.auth.tenant_context import TenantContext

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("")
def list_applications(context: TenantContext = Depends(tenant_context)):
    return [
        application.public_dict()
        for application in application_repository.list(context.tenant_id)
    ]