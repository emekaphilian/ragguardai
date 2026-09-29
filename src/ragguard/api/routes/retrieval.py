from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from ragguard.auth.tenant_context import TenantContext
from ragguard.api.middleware import tenant_context
from ragguard.api.schemas import DocumentRequest, QueryRequest, QueryResponse
from ragguard.api.runtime import workspace
from ragguard.ingestion.file_extractors import UnsupportedDocumentType, extract_text

router = APIRouter()

@router.post("/query", response_model=QueryResponse)
def query(request: QueryRequest, context: TenantContext = Depends(tenant_context)):
    return QueryResponse(**workspace.query(request.query, request.top_k, request.method, context=context))

@router.get("/documents")
def documents(context: TenantContext = Depends(tenant_context)):
    return workspace.document_rows(context)

@router.delete("/documents/{document_id}")
def delete_document(document_id: str, context: TenantContext = Depends(tenant_context)):
    if not workspace.delete_document(document_id, context=context):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"id": document_id, "deleted": True}

@router.post("/documents")
def add_document(request: DocumentRequest, context: TenantContext = Depends(tenant_context)):
    return workspace.add_document(request.name, request.text, context=context, ingestion_method="pasted")


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    context: TenantContext = Depends(tenant_context),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="A document file is required")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The document is empty")

    try:
        text = extract_text(file.filename, content)
    except UnsupportedDocumentType as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not read the document") from exc

    if not text.strip():
        raise HTTPException(status_code=400, detail="The document contains no extractable text")

    return workspace.add_document(file.filename, text, context=context, ingestion_method="uploaded")
