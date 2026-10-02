from pathlib import Path

p = Path("src/ragguard/api/routes/retrieval.py")
s = p.read_text()

s = s.replace(
    "from fastapi import APIRouter, Depends, File, HTTPException, UploadFile",
    "from dataclasses import replace\n\nfrom fastapi import APIRouter, Depends, File, HTTPException, UploadFile",
)

s = s.replace(
    "from ragguard.api.schemas import DocumentRequest, QueryRequest, QueryResponse",
    "from ragguard.api.schemas import DocumentRequest, QueryRequest, QueryResponse\nfrom ragguard.api.external_query import query_external_application",
)

s = s.replace(
    "from ragguard.api.runtime import workspace",
    "from ragguard.api.runtime import application_repository, workspace",
)

old = """def query(request: QueryRequest, context: TenantContext = Depends(tenant_context)):
    return QueryResponse(**workspace.query(request.query, request.top_k, request.method, context=context))
"""

new = """def query(request: QueryRequest, context: TenantContext = Depends(tenant_context)):
    application_id = request.application_id or context.application_id
    environment = request.environment or context.environment

    application = application_repository.get(
        context.tenant_id,
        application_id,
        environment,
    )

    if application is None:
        raise HTTPException(
            status_code=404,
            detail="Application is not registered for this RAGGuard tenant and environment.",
        )

    if not application.queryable:
        raise HTTPException(
            status_code=409,
            detail="This application is registered for observations only and cannot be queried from Query Lab.",
        )

    if application.knowledge_source == "external_rag_api":
        return QueryResponse(
            **query_external_application(
                application,
                query=request.query,
                top_k=request.top_k,
                method=request.method,
            )
        )

    application_context = replace(
        context,
        application_id=application.application_id,
        environment=application.environment,
        vector_namespace=application.vector_namespace or context.vector_namespace,
    )

    return QueryResponse(
        **workspace.query(
            request.query,
            request.top_k,
            request.method,
            context=application_context,
            record_run=request.record_run,
        )
    )
"""

if old not in s:
    raise SystemExit("ERROR: expected query function was not found")

p.write_text(s.replace(old, new))
print("Query Lab route updated.")
