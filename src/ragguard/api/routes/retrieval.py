from fastapi import APIRouter, Depends
from ragguard.auth.tenant_context import TenantContext
from ragguard.api.middleware import tenant_context
from ragguard.api.schemas import DocumentRequest, QueryRequest, QueryResponse
from ragguard.api.runtime import workspace

router = APIRouter()

@router.post("/query", response_model=QueryResponse)
def query(request: QueryRequest, context: TenantContext = Depends(tenant_context)):
    return QueryResponse(**workspace.query(request.query, request.top_k, request.method, context=context))

@router.get("/documents")
def documents(context: TenantContext = Depends(tenant_context)):
    return workspace.document_rows(context)

@router.post("/documents")
def add_document(request: DocumentRequest, context: TenantContext = Depends(tenant_context)):
    return workspace.add_document(request.name, request.text, context=context)
