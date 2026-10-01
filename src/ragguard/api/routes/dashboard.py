from fastapi import APIRouter, Depends, Query

from ragguard.api.observation_views import observation_failure, observation_run
from ragguard.api.runtime import observation_repository, workspace
from ragguard.auth.tenant_context import TenantContext
from ragguard.api.middleware import tenant_context

router = APIRouter()


@router.get('/dashboard')
def dashboard(context: TenantContext = Depends(tenant_context)):
    result = workspace.dashboard(context)
    filters = {
        "ragguard_tenant_id": context.tenant_id,
        "application_id": context.application_id,
    }
    observation_count = observation_repository.count(**filters)
    observation_failures = observation_repository.count(
        **filters,
        failure_detected=True,
    )
    metrics = result["metrics"]
    metrics["total_runs"] += observation_count
    metrics["total_failures"] += observation_failures
    metrics["observation_runs"] = observation_count
    metrics["observation_failures"] = observation_failures
    metrics["failure_rate"] = (
        round(metrics["total_failures"] / metrics["total_runs"], 3)
        if metrics["total_runs"]
        else None
    )

    recent = [
        *result["recent_failures"],
        *[
            observation_failure(record)
            for record in observation_repository.list(
                **filters,
                failure_detected=True,
                limit=10,
            )
        ],
    ]
    result["recent_failures"] = sorted(
        recent,
        key=lambda item: item["created_at"],
        reverse=True,
    )[:10]
    recent_runs = [
        *[
            {**run, "source": "workspace"}
            for run in workspace.runs
            if run["tenant_id"] == context.tenant_id
        ][:10],
        *[
            observation_run(record)
            for record in observation_repository.list(**filters, limit=10)
        ],
    ]
    result["recent_runs"] = sorted(
        recent_runs,
        key=lambda item: item["created_at"],
        reverse=True,
    )[:10]
    return result


@router.get('/runs')
def runs(
    context: TenantContext = Depends(tenant_context),
    limit: int = Query(default=50, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
):
    local_runs = [
        {**run, "source": "workspace"}
        for run in workspace.runs
        if run["tenant_id"] == context.tenant_id
    ]
    observation_records = observation_repository.list(
        ragguard_tenant_id=context.tenant_id,
        application_id=context.application_id,
        limit=limit + offset,
    )
    combined = [
        *local_runs,
        *(observation_run(record) for record in observation_records),
    ]
    combined.sort(key=lambda item: item["created_at"], reverse=True)
    return combined[offset:offset + limit]
