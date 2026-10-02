from hmac import compare_digest
import os
import re
from dataclasses import replace
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query

from ragguard.api.runtime import application_repository, observation_repository, workspace
from ragguard.api.routes.observations import recovery_repository
from ragguard.api.schemas import ApplicationRegistrationRequest
from ragguard.config import load_settings
from ragguard.tenants.application_registration import ApplicationRegistration
from ragguard.tenants.service import TenantService

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(authorization: str | None) -> None:
    admin_token = os.getenv("RAGGUARD_ADMIN_TOKEN")
    if not admin_token:
        raise HTTPException(status_code=503, detail="Administrative access is not configured.")
    scheme, _, supplied_token = (authorization or "").partition(" ")
    if (
        scheme.lower() != "bearer"
        or not supplied_token
        or not compare_digest(supplied_token, admin_token)
    ):
        raise HTTPException(status_code=401, detail="Invalid administrator credential.")


def _registration_from_request(
    request: ApplicationRegistrationRequest,
) -> ApplicationRegistration:
    try:
        TenantService(load_settings()).resolve(request.ragguard_tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="RAGGuard tenant is not configured.") from exc

    if request.knowledge_source == "managed_index" and not request.vector_namespace:
        raise HTTPException(status_code=422, detail="managed_index requires vector_namespace.")
    if not request.observation_token_env_var:
        raise HTTPException(status_code=422, detail="Every registered application must configure an observation credential.")
    if request.knowledge_source == "observation_only" and request.vector_namespace:
        raise HTTPException(status_code=422, detail="observation_only cannot have a managed vector namespace.")
    if request.knowledge_source == "external_rag_api":
        parsed = urlparse(request.query_endpoint_url or "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(status_code=422, detail="External query endpoints must use HTTPS without URL credentials.")
    elif request.query_endpoint_url or request.query_token_env_var:
        raise HTTPException(
            status_code=422,
            detail="External query endpoint settings require knowledge_source=external_rag_api.",
        )

    for variable_name in (
        request.query_token_env_var,
        request.observation_token_env_var,
    ):
        if variable_name is not None and not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", variable_name):
            raise HTTPException(status_code=422, detail="Credential references must be environment variable names.")

    return ApplicationRegistration(**request.model_dump())


@router.delete("/history")
def clear_history(
    authorization: str | None = Header(default=None),
    confirmation: str | None = Header(default=None, alias="X-Confirm-Delete"),
):
    """Clear persisted and in-memory activity after explicit admin confirmation."""
    _require_admin(authorization)

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


@router.get("/applications")
def list_registered_applications(
    ragguard_tenant_id: str = Query(min_length=1),
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization)
    return [
        application.public_dict()
        for application in application_repository.list(
            ragguard_tenant_id,
            active_only=False,
        )
    ]


@router.put("/applications")
def upsert_application(
    request: ApplicationRegistrationRequest,
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization)
    application = _registration_from_request(request)
    return application_repository.upsert(application).public_dict()


@router.post("/applications/bootstrap-configured")
def bootstrap_configured_applications(
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization)
    inserted = application_repository.bootstrap(load_settings().tenant_policies)
    return {"inserted": inserted}


@router.delete("/applications/{ragguard_tenant_id}/{application_id}/{environment}")
def deactivate_application(
    ragguard_tenant_id: str,
    application_id: str,
    environment: str,
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization)
    application = application_repository.get(
        ragguard_tenant_id,
        application_id,
        environment,
        active_only=False,
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Registered application not found.")
    return application_repository.upsert(replace(application, active=False)).public_dict()
