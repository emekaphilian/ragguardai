from hmac import compare_digest
from hashlib import sha256
import os
import re
import secrets
from dataclasses import replace
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ragguard.api.runtime import application_repository, observation_repository, workspace, auth_repository
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


class TenantMembershipRequest(BaseModel):
    issuer: str = Field(min_length=1, max_length=512)
    subject: str = Field(min_length=1, max_length=512)
    tenant_id: str = Field(min_length=1, max_length=200)
    roles: list[str] = Field(default_factory=list)


def _require_admin(
    authorization: str | None,
    request: Request | None = None,
    tenant_id: str | None = None,
    *,
    allow_session: bool = True,
) -> None:
    admin_token = os.getenv("RAGGUARD_ADMIN_TOKEN")
    scheme, _, supplied_token = (authorization or "").partition(" ")
    if admin_token and scheme.lower() == "bearer" and supplied_token and compare_digest(supplied_token, admin_token):
        return
    settings = load_settings()
    if allow_session and request is not None and settings.authentication.mode == "oidc":
        session_id = request.cookies.get(settings.authentication.session_cookie_name)
        session = auth_repository.get_session(session_id) if session_id else None
        csrf = request.headers.get("X-CSRF-Token", "")
        csrf_hash = sha256(csrf.encode()).hexdigest()
        if not session or not csrf or not compare_digest(session.get("csrf_hash", ""), csrf_hash):
            raise HTTPException(status_code=403, detail="Authenticated administrator session and valid CSRF token required.")
        scope = tenant_id or settings.service_auth.tenant_id
        roles = auth_repository.get_membership(session["issuer"], session["subject"], scope)
        if roles and ({role.lower() for role in roles} & {"admin", "owner", "workspace_admin"}):
            return
        raise HTTPException(status_code=403, detail="Administrator permission is required for this tenant.")
    if not admin_token:
        raise HTTPException(status_code=503, detail="Administrative access is not configured.")
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
    request: Request,
    authorization: str | None = Header(default=None),
    confirmation: str | None = Header(default=None, alias="X-Confirm-Delete"),
):
    """Clear persisted and in-memory activity after explicit admin confirmation."""
    _require_admin(authorization, request, allow_session=False)

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
    request_obj: Request,
    payload: ApplicationOnboardingRequest,
    authorization: str | None = Header(default=None),
):
    """Register an observation-only app and issue its credential once."""
    settings = load_settings()
    tenant_id = payload.ragguard_tenant_id or settings.service_auth.tenant_id
    _require_admin(authorization, request_obj, tenant_id)
    _resolve_tenant(tenant_id)
    if application_repository.get(
        tenant_id,
        payload.application_id,
        payload.environment,
        active_only=False,
    ) is not None:
        raise HTTPException(
            status_code=409,
            detail="This application and environment are already registered. Use credential rotation if access must change.",
        )

    token, token_hash = _new_observation_credential()
    application = application_repository.upsert(ApplicationRegistration(
        ragguard_tenant_id=tenant_id,
        application_id=payload.application_id,
        display_name=payload.display_name,
        environment=payload.environment,
        knowledge_source="observation_only",
        observation_token_hash=token_hash,
        repair_authorized=False,
        context_verification_authorized=False,
        independent_verification_authorized=False,
    ))
    return _credential_response(application, token)


@router.post("/applications/{ragguard_tenant_id}/{application_id}/{environment}/observation-credential")
def rotate_observation_credential(
    request: Request,
    ragguard_tenant_id: str,
    application_id: str,
    environment: str,
    authorization: str | None = Header(default=None),
):
    """Replace an application's observation credential and show it once."""
    _require_admin(authorization, request, ragguard_tenant_id)
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
    request: Request,
    ragguard_tenant_id: str = Query(min_length=1),
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization, request, ragguard_tenant_id)
    return [
        application.public_dict()
        for application in application_repository.list(
            ragguard_tenant_id,
            active_only=False,
        )
    ]


@router.put("/applications")
def upsert_application(
    http_request: Request,
    request: ApplicationRegistrationRequest,
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization, http_request, request.ragguard_tenant_id)
    application = _registration_from_request(request)
    return application_repository.upsert(application).public_dict()


@router.patch("/applications/{ragguard_tenant_id}/{application_id}/{environment}/capabilities")
def update_application_capabilities(
    http_request: Request,
    ragguard_tenant_id: str,
    application_id: str,
    environment: str,
    request: ApplicationCapabilityUpdateRequest,
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization, http_request, ragguard_tenant_id)
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
    request: Request,
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization, request, allow_session=False)
    inserted = application_repository.bootstrap(load_settings().tenant_policies)
    return {"inserted": inserted}


@router.delete("/applications/{ragguard_tenant_id}/{application_id}/{environment}")
def deactivate_application(
    request: Request,
    ragguard_tenant_id: str,
    application_id: str,
    environment: str,
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization, request, ragguard_tenant_id)
    application = application_repository.get(
        ragguard_tenant_id,
        application_id,
        environment,
        active_only=False,
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Registered application not found.")
    return application_repository.upsert(replace(application, active=False)).public_dict()


@router.put("/tenant-memberships")
def grant_tenant_membership(
    request: Request,
    membership: TenantMembershipRequest,
    authorization: str | None = Header(default=None),
):
    """Create or replace a server-owned tenant grant; IdP role claims are ignored."""
    _require_admin(authorization, request, membership.tenant_id)
    if membership.issuer != load_settings().authentication.oidc_issuer:
        raise HTTPException(status_code=422, detail="Membership issuer must match the configured OIDC issuer.")
    normalized_roles = tuple(sorted({role.strip().lower() for role in membership.roles if role.strip()}))
    allowed_roles = {"reader", "operator", "admin", "owner", "workspace_admin"}
    if not normalized_roles or not set(normalized_roles) <= allowed_roles:
        raise HTTPException(status_code=422, detail="Membership contains an unsupported role.")
    _resolve_tenant(membership.tenant_id)
    auth_repository.grant_membership(membership.issuer, membership.subject, membership.tenant_id, normalized_roles)
    return {"issuer": membership.issuer, "subject": membership.subject, "tenant_id": membership.tenant_id, "roles": list(normalized_roles)}


@router.get("/tenant-memberships")
def list_tenant_memberships(
    request: Request,
    tenant_id: str = Query(min_length=1),
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization, request, tenant_id)
    return auth_repository.list_memberships(tenant_id)


@router.delete("/tenant-memberships")
def revoke_tenant_membership(
    request: Request,
    issuer: str = Query(min_length=1),
    subject: str = Query(min_length=1),
    tenant_id: str = Query(min_length=1),
    authorization: str | None = Header(default=None),
):
    _require_admin(authorization, request, tenant_id)
    auth_repository.revoke_membership(issuer, subject, tenant_id)
    return {"revoked": True, "issuer": issuer, "subject": subject, "tenant_id": tenant_id}
