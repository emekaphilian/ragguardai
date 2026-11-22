from fastapi import APIRouter, Depends, Query

from ragguard.auth.application_access import visible_applications
from ragguard.api.observation_views import observation_failure, observation_run
from ragguard.api.runtime import application_repository, observation_repository, workspace
from ragguard.auth.tenant_context import TenantContext
from ragguard.api.middleware import tenant_context

router = APIRouter()


def dashboard_data(context: TenantContext) -> dict:
    result = workspace.dashboard(context)
    filters = {
        "ragguard_tenant_id": context.tenant_id,
        "application_id": context.application_id,
        "environment": context.environment,
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
    metrics["observed_reliability_event_rate"] = (
        round(observation_failures / observation_count, 3)
        if observation_count
        else None
    )
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
            and run.get("application_id") == context.application_id
            and run.get("environment") == context.environment
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
    result["scope"] = {
        "ragguard_tenant_id": context.tenant_id,
        "application_id": context.application_id,
        "environment": context.environment,
    }
    result["metric_semantics"] = {
        "term_match": "lexical query-term overlap proxy; not a labeled relevance score",
        "source_coverage": "retrieval-threshold proxy; not answer citation coverage",
        "answer_relevancy": "local lexical similarity proxy; not a labeled relevance judgment",
        "faithfulness": "local context overlap proxy; not a semantic entailment check",
        "citation_accuracy": "default metric value; no citation verifier runs in this local workspace path",
        "overall_quality": "mean of available local proxy metrics",
        "embedding_model": "local TF-IDF retrieval model; not a neural embedding model",
        "observed_reliability_event_rate": "fraction of observed requests classified as failures by configured rules",
    }
    return result


@router.get('/dashboard')
def dashboard(context: TenantContext = Depends(tenant_context)):
    return dashboard_data(context)


@router.get('/runs')
def runs(
    context: TenantContext = Depends(tenant_context),
    limit: int = Query(default=50, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
    application_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
    failure_detected: bool | None = Query(default=None),
):
    registered_applications = visible_applications(
        context,
        application_repository.list(context.tenant_id),
    )
    scoped_applications = [
        application
        for application in registered_applications
        if (application_id is None or application.application_id == application_id)
        and (environment is None or application.environment == environment)
    ]
    if application_id is not None and not scoped_applications:
        return []

    scopes = {
        (application.application_id, application.environment)
        for application in scoped_applications
    }

    local_runs = [
        {**run, "source": "workspace"}
        for run in workspace.runs
        if run["tenant_id"] == context.tenant_id
        and (run.get("application_id"), run.get("environment")) in scopes
        and (status is None or run.get("status") == status)
        and (
            failure_detected is None
            or (run.get("status") == "no_match") is failure_detected
        )
    ]
    observation_records = [
        record
        for application in scoped_applications
        for record in observation_repository.list(
            ragguard_tenant_id=context.tenant_id,
            application_id=application.application_id,
            environment=application.environment,
            status=status,
            failure_detected=failure_detected,
            limit=limit + offset,
        )
    ]
    combined = [
        *local_runs,
        *(observation_run(record) for record in observation_records),
    ]
    combined.sort(key=lambda item: item["created_at"], reverse=True)
    return combined[offset:offset + limit]
