from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ragguard.api.middleware import tenant_context
from ragguard.api.schemas import RecoveryAuditPageResponse, RecoveryAuditResponse
from ragguard.auth.tenant_context import TenantContext
from ragguard.config import load_settings
from ragguard.observability.recovery_audit import record_to_dict
from ragguard.observability.recovery_repository import RecoveryAuditRepository


def build_recovery_router(
    repository: RecoveryAuditRepository,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/recoveries",
        tags=["recovery-observability"],
    )

    @router.get("", response_model=RecoveryAuditPageResponse)
    def list_recoveries(
        tenant_id: str | None = Query(default=None),
        application_id: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1),
        context: TenantContext = Depends(tenant_context),
    ):
        max_page_size = load_settings().audit_max_page_size
        if page_size > max_page_size:
            raise HTTPException(
                status_code=422,
                detail=f"page_size must not exceed {max_page_size}.",
            )
        if application_id is not None and application_id != context.application_id:
            raise HTTPException(status_code=403, detail="Application access denied.")

        filters = {
            "ragguard_tenant_id": context.tenant_id,
            "tenant_id": tenant_id,
            "application_id": context.application_id,
        }
        total = repository.count(**filters)
        records = repository.list(
            **filters,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {
            "items": [record_to_dict(record) for record in records],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_next": page * page_size < total,
        }

    @router.get("/{recovery_id}", response_model=RecoveryAuditResponse)
    def get_recovery(
        recovery_id: str,
        context: TenantContext = Depends(tenant_context),
    ):
        record = repository.get(recovery_id)
        if (
            record is None
            or record.ragguard_tenant_id != context.tenant_id
            or record.application_id != context.application_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Recovery record not found.",
            )
        return record_to_dict(record)

    return router
