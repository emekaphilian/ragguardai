from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ragguard.api.middleware import tenant_context
from ragguard.api.routes.observations import recovery_repository
from ragguard.auth.tenant_context import TenantContext
from ragguard.replay.models import ReplayRequest, ReplayResult
from ragguard.replay.service import (
    RecoveryReplayService,
    ReplayNotFoundError,
    ReplayUnavailableError,
)

router = APIRouter(prefix="/api/v1/replays", tags=["recovery-replay"])
replay_service = RecoveryReplayService(recovery_repository)


@router.post("", response_model=ReplayResult)
def replay_recovery(
    request: ReplayRequest,
    context: TenantContext = Depends(tenant_context),
):
    try:
        return replay_service.replay(request, context=context)
    except ReplayNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReplayUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
