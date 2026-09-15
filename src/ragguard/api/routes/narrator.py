from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ragguard.narrator import generate_narration
from ragguard.auth.tenant_context import TenantContext
from ragguard.api.middleware import tenant_context

router = APIRouter()


class NarrateRequest(BaseModel):
    page: str = Field(min_length=1)
    data: dict = {}


@router.post('/narrate')
def narrator(request: NarrateRequest, context: TenantContext = Depends(tenant_context)):
    return generate_narration(request.page, request.data, context=context)
