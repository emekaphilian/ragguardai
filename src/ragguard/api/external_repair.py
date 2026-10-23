from __future__ import annotations

import json
import os
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ragguard.api.external_query import _validate_public_endpoint
from ragguard.common.enums import RepairType
from ragguard.evaluation.live import RAGObservation
from ragguard.tenants.application_registration import ApplicationRegistration

MAX_REPAIR_RESPONSE_BYTES = 256_000
SUPPORTED_REMOTE_REPAIRS = frozenset({
    RepairType.DEDUPLICATE,
    RepairType.HYBRID_RETRIEVAL,
    RepairType.RERANK,
})


class ExternalRepairError(RuntimeError):
    """A remote repair adapter failed or returned an invalid contract response."""


class ExternalRepairCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"]
    supported_repairs: list[RepairType] = Field(max_length=16)


class ExternalRepairRetrievedChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    score: float = Field(allow_inf_nan=False)


class ExternalRepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    request_id: str = Field(min_length=1, max_length=200)
    application_id: str = Field(min_length=1, max_length=100)
    environment: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=20_000)
    failure_type: str = Field(min_length=1, max_length=80)
    strategy: Literal["DEDUPLICATE", "HYBRID_RETRIEVAL", "RERANK"]
    retrieved_chunks: list[ExternalRepairRetrievedChunk] = Field(max_length=500)


class ExternalRepairResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"]
    request_id: str = Field(min_length=1, max_length=200)
    strategy: Literal["DEDUPLICATE", "HYBRID_RETRIEVAL", "RERANK"]
    status: Literal["promoted", "rejected", "rolled_back"]
    validated: bool
    context_verified: bool
    improvement: float | None = Field(default=None, allow_inf_nan=False)


def _credentials(application: ApplicationRegistration) -> tuple[str, str]:
    endpoint = application.repair_endpoint_url
    variable = application.repair_token_env_var
    if not endpoint or not variable:
        raise ExternalRepairError("The external repair adapter is not configured.")
    token = os.getenv(variable)
    if not token:
        raise ExternalRepairError(
            "The external repair adapter credential is not configured on the server."
        )
    return endpoint, token


def _read_response(response: httpx.Response) -> bytes:
    if response.is_redirect:
        raise ExternalRepairError("External repair adapter redirects are not supported.")
    response.raise_for_status()
    body = bytearray()
    for part in response.iter_bytes():
        body.extend(part)
        if len(body) > MAX_REPAIR_RESPONSE_BYTES:
            raise ExternalRepairError("External repair response exceeded the size limit.")
    return bytes(body)


def _decode_response(body: bytes, model):
    try:
        return model.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ExternalRepairError(
            "External repair response did not match contract v1."
        ) from exc


def _request(
    *,
    method: str,
    url: str,
    token: str,
    json_body: dict | None = None,
    request_id: str | None = None,
):
    try:
        _validate_public_endpoint(url)
    except HTTPException as exc:
        raise ExternalRepairError(
            "External repair adapter endpoint could not be validated safely."
        ) from exc
    headers = {"Authorization": f"Bearer {token}"}
    if request_id:
        headers["Idempotency-Key"] = request_id
    try:
        with httpx.Client(
            timeout=10.0,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            with client.stream(
                method,
                url,
                headers=headers,
                json=json_body,
            ) as response:
                return _read_response(response)
    except ExternalRepairError:
        raise
    except httpx.HTTPError as exc:
        raise ExternalRepairError("External repair adapter request failed.") from exc


def get_supported_repairs(application: ApplicationRegistration) -> frozenset[RepairType]:
    endpoint, token = _credentials(application)
    capability_url = f"{endpoint.rstrip('/')}/capabilities"
    body = _request(
        method="GET",
        url=capability_url,
        token=token,
    )
    response = _decode_response(body, ExternalRepairCapabilities)
    return frozenset(response.supported_repairs) & SUPPORTED_REMOTE_REPAIRS


def request_external_repair(
    application: ApplicationRegistration,
    observation: RAGObservation,
    *,
    failure_type: str,
    strategy: RepairType,
) -> ExternalRepairResult:
    if strategy not in SUPPORTED_REMOTE_REPAIRS:
        raise ExternalRepairError("The requested repair strategy is not supported.")
    endpoint, token = _credentials(application)
    request_id = observation.request_id or str(uuid4())
    try:
        request = ExternalRepairRequest(
            request_id=request_id,
            application_id=application.application_id,
            environment=application.environment,
            query=observation.query,
            failure_type=failure_type,
            strategy=strategy.value,
            retrieved_chunks=[
                {"id": chunk.id, "score": chunk.score}
                for chunk in observation.retrieved_chunks
            ],
        )
    except ValueError as exc:
        raise ExternalRepairError(
            "Observation exceeded the external repair contract limits."
        ) from exc
    body = _request(
        method="POST",
        url=endpoint,
        token=token,
        json_body=request.model_dump(mode="json"),
        request_id=request_id,
    )
    result = _decode_response(body, ExternalRepairResult)
    if result.request_id != request_id or result.strategy != strategy.value:
        raise ExternalRepairError(
            "External repair response did not match the requested operation."
        )
    if result.status == "promoted" and not result.validated:
        raise ExternalRepairError(
            "External repair adapter promoted a result without validation."
        )
    if result.status == "promoted" and not result.context_verified:
        raise ExternalRepairError(
            "External repair adapter promoted a result without context verification."
        )
    if (
        result.status == "promoted"
        and (result.improvement is None or result.improvement <= 0)
    ):
        raise ExternalRepairError(
            "External repair adapter promoted a result without measured improvement."
        )
    return result
