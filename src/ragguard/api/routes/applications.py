from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from ragguard.api.middleware import tenant_context
from ragguard.api.runtime import application_repository, observation_repository
from ragguard.auth.tenant_context import TenantContext

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("")
def list_applications(context: TenantContext = Depends(tenant_context)):
    applications = application_repository.list(context.tenant_id)
    result = []
    for application in applications:
        latest_observation = observation_repository.list(
            ragguard_tenant_id=context.tenant_id,
            application_id=application.application_id,
            environment=application.environment,
            limit=1,
        )
        last_observed_at = (
            latest_observation[0].created_at.isoformat()
            if latest_observation
            else None
        )
        last_observed = latest_observation[0].created_at if latest_observation else None
        is_recent = bool(
            last_observed
            and last_observed >= datetime.now(timezone.utc) - timedelta(hours=24)
        )
        result.append({
            "ragguard_tenant_id": context.tenant_id,
            **application.public_dict(),
            "connection_status": (
                "connected" if is_recent else "stale" if last_observed_at else "waiting_for_data"
            ),
            "last_observed_at": last_observed_at,
            "last_evaluation_status": latest_observation[0].status if latest_observation else None,
        })
    return result
