from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ragguard.auth.application_access import application_is_allowed
from ragguard.api.middleware import tenant_context
from ragguard.api.runtime import application_repository
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
        environment: str | None = Query(default=None),
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
        if context.application_memberships is None:
            scopes = {
                (application.application_id, application.environment)
                for application in application_repository.list(context.tenant_id, active_only=False)
            }
        else:
            scopes = {
                (application, app_environment)
                for application, app_environment, _ in context.application_memberships
            }
        scopes = {
            (application, app_environment)
            for application, app_environment in scopes
            if (application_id is None or application == application_id)
            and (environment is None or app_environment == environment)
        }
        if application_id is not None and not scopes:
            raise HTTPException(status_code=404, detail="Application not found for this RAGGuard tenant.")
        offset = (page - 1) * page_size
        total = 0
        records = []
        if context.application_memberships is None and application_id is None:
            # Platform tenant admins can inspect historical records even if an
            # application registration has since been removed.
            filters = {
                "ragguard_tenant_id": context.tenant_id,
                "tenant_id": tenant_id,
                "environment": environment,
            }
            total = repository.count(**filters)
            records = repository.list(**filters, limit=offset + page_size, offset=0)
        for application, app_environment in scopes if not (
            context.application_memberships is None and application_id is None
        ) else ():
            filters = {
                "ragguard_tenant_id": context.tenant_id,
                "tenant_id": tenant_id,
                "application_id": application,
                "environment": app_environment,
            }
            total += repository.count(**filters)
            records.extend(repository.list(
                **filters,
                limit=offset + page_size,
                offset=0,
            ))
        records.sort(key=lambda record: record.started_at, reverse=True)
        records = records[offset:offset + page_size]
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
            or not application_is_allowed(
                context,
                record.application_id or "",
                record.environment,
            )
        ):
            raise HTTPException(
                status_code=404,
                detail="Recovery record not found.",
            )
        response = record_to_dict(record)
        snapshot = record.observation_snapshot or {}
        response.update({
            "query": snapshot.get("query"),
            "retrieval_method": snapshot.get("retrieval_method"),
            "embedding_degraded": snapshot.get("embedding_degraded"),
            "retrieved_chunks": [
                {
                    "id": chunk.get("id"),
                    "score": chunk.get("score"),
                }
                for chunk in snapshot.get("retrieved_chunks", [])
                if isinstance(chunk, dict)
            ],
        })
        return response

    return router
