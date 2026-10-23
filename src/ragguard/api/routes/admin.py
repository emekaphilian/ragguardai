from hmac import compare_digest
from hashlib import sha256
import os
import re
import secrets
from dataclasses import replace
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query

from ragguard.api.runtime import application_repository, observation_repository, workspace
from ragguard.api.routes.observations import recovery_repository
from ragguard.api.schemas import (
    ApplicationOnboardingRequest,
    ApplicationCapabilityUpdateRequest,
    ApplicationRegistrationRequest,
)
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

    if bool(request.repair_endpoint_url) != bool(request.repair_token_env_var):
        raise HTTPException(
            status_code=422,
            detail="External repair endpoints require a separate repair credential reference.",
        )
    if request.repair_endpoint_url:
        if request.knowledge_source not in {"external_rag_api", "observation_only"}:
            raise HTTPException(
                status_code=422,
                detail="External repair adapters require an external application registration.",
            )
        repair_url = urlparse(request.repair_endpoint_url)
        if (
            repair_url.scheme != "https"
            or not repair_url.hostname
            or repair_url.username
            or repair_url.password
            or repair_url.query
            or repair_url.fragment
        ):
            raise HTTPException(
                status_code=422,
                detail="External repair endpoints must use HTTPS without URL credentials, query, or fragment.",
            )

    for variable_name in (
        request.query_token_env_var,
        request.repair_token_env_var,
        request.observation_token_env_var,
    ):
        if variable_name is not None and not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", variable_name):
            raise HTTPException(status_code=422, detail="Credential references must be environment variable names.")

    existing = application_repository.get(
        request.ragguard_tenant_id,
        request.application_id,
        request.environment,
        active_only=False,
    )

    authorization_state = {}
    if existing is not None:
        authorization_state = {
            "repair_authorized": existing.repair_authorized,
            "context_verification_authorized": existing.context_verification_authorized,
            "independent_verification_authorized": existing.independent_verification_authorized,
            "observation_token_hash": existing.observation_token_hash,
        }

    return ApplicationRegistration(
        **request.model_dump(),
        **authorization_state,
    )


def _new_observation_credential() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, sha256(token.encode("utf-8")).hexdigest()


def _resolve_tenant(tenant_id: str) -> None:
    try:
        TenantService(load_settings()).resolve(tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="RAGGuard tenant is not configured.") from exc


def _credential_response(application: ApplicationRegistration, token: str) -> dict:
    return {
        **application.public_dict(),
        "observation_credential": token,
        "credential_notice": "Copy this credential now. RAGGuard stores only its hash and cannot show it again.",
    }


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


@router.post("/applications/onboard", status_code=201)
def onboard_observation_application(
    request: ApplicationOnboardingRequest,
    authorization: str | None = Header(default=None),
):
    """Register an observation-only app and issue its credential once."""
    _require_admin(authorization)
    settings = load_settings()
    tenant_id = request.ragguard_tenant_id or settings.service_auth.tenant_id
    _resolve_tenant(tenant_id)
    if application_repository.get(
        tenant_id,
        request.application_id,
        request.environment,
        active_only=False,
    ) is not None:
        raise HTTPException(
            status_code=409,
            detail="This application and environment are already registered. Use credential rotation if access must change.",
        )

    token, token_hash = _new_observation_credential()
    application = application_repository.upsert(ApplicationRegistration(
        ragguard_tenant_id=tenant_id,
        application_id=request.application_id,
        display_name=request.display_name,
        environment=request.environment,
        knowledge_source="observation_only",
        observation_token_hash=token_hash,
        repair_authorized=False,
        context_verification_authorized=False,
        independent_verification_authorized=False,
    ))
    return _credential_response(application, token)


@router.post("/applications/{ragguard_tenant_id}/{application_id}/{environment}/observation-credential")
def rotate_observation_credential(
    ragguard_tenant_id: str,
    application_id: str,
    environment: str,
    authorization: str | None = Header(default=None),
):
    """Replace an application's observation credential and show it once."""
    _require_admin(authorization)
    _resolve_tenant(ragguard_tenant_id)
    application = application_repository.get(
        ragguard_tenant_id,
        application_id,
        environment,
        active_only=False,
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Registered application not found.")
    token, token_hash = _new_observation_credential()
    updated = replace(
        application,
        observation_token_env_var=None,
        observation_token_hash=token_hash,
    )
    application_repository.upsert(updated)
    return _credential_response(updated, token)


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


@router.patch("/applications/{ragguard_tenant_id}/{application_id}/{environment}/capabilities")
def update_application_capabilities(
    ragguard_tenant_id: str,
    application_id: str,
    environment: str,
    request: ApplicationCapabilityUpdateRequest,
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

    updated_application = replace(
        application,
        context_verification_authorized=request.context_verification_authorized,
        independent_verification_authorized=request.independent_verification_authorized,
        repair_authorized=request.repair_authorized,
    )
    return application_repository.upsert(updated_application).public_dict()


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
