from hmac import compare_digest
import os

from fastapi import APIRouter, Header, HTTPException

from ragguard.api.runtime import observation_repository, workspace
from ragguard.api.routes.observations import recovery_repository

router = APIRouter(prefix="/admin", tags=["admin"])


@router.delete("/history")
def clear_history(
    authorization: str | None = Header(default=None),
    confirmation: str | None = Header(default=None, alias="X-Confirm-Delete"),
):
    """Clear persisted and in-memory activity after explicit admin confirmation."""
    admin_token = os.getenv("RAGGUARD_ADMIN_TOKEN")
    if not admin_token:
        raise HTTPException(
            status_code=503,
            detail="Administrative history clearing is not configured.",
        )

    scheme, _, supplied_token = (authorization or "").partition(" ")
    if (
        scheme.lower() != "bearer"
        or not supplied_token
        or not compare_digest(supplied_token, admin_token)
    ):
        raise HTTPException(status_code=401, detail="Invalid administrator credential.")

    if confirmation != "clear-all-history":
        raise HTTPException(
            status_code=400,
            detail="Set X-Confirm-Delete: clear-all-history to confirm.",
        )

    deleted_observations = observation_repository.clear()
    deleted_recoveries = recovery_repository.clear()
    workspace_counts = {
        "runs": len(workspace.runs),
        "failures": len(workspace.failures),
        "repairs": len(workspace.repairs),
    }
    workspace.runs.clear()
    workspace.failures.clear()
    workspace.repairs.clear()
    return {
        "deleted_observations": deleted_observations,
        "deleted_recoveries": deleted_recoveries,
        "deleted_workspace_runs": workspace_counts["runs"],
        "deleted_workspace_failures": workspace_counts["failures"],
        "deleted_workspace_repairs": workspace_counts["repairs"],
    }
