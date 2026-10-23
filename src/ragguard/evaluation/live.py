from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class RetrievedChunkObservation(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    score: float


class ObservationSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: str = Field(min_length=1, max_length=100)
    environment: str = Field(min_length=1, max_length=80)
    source_tenant_id: str | None = Field(default=None, min_length=1, max_length=200)


class RAGObservation(BaseModel):
    """Application-neutral snapshot of one RAG retrieval and answer."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"]
    source: ObservationSource
    query: str = Field(min_length=1)
    request_id: str | None = Field(default=None, min_length=1, max_length=200)
    retrieved_chunks: list[RetrievedChunkObservation] = Field(default_factory=list)
    retrieval_method: str = "unknown"
    retrieval_required: bool | None = None
    retrieval_attempted: bool | None = None
    embedding_degraded: bool = False
    retrieval_latency_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    stage_timings_ms: dict[str, Annotated[float, Field(ge=0, allow_inf_nan=False)]] = Field(
        default_factory=dict
    )
    evidence_sufficient: bool | None = None
    generation_status: Literal["succeeded", "failed", "skipped"] | None = None
    failed_stage: Literal[
        "retrieval",
        "embedding",
        "generation",
        "database",
        "external_service",
        "unknown",
    ] | None = None
    error_code: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    answer: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    # Compatibility fields for existing RAGGuard internal callers.
    embedding_fallback: bool = False
    embedding_failure: bool = False


# Historical name retained while internal integrations migrate.
RAGGuardObservation = RAGObservation


class LiveEvaluation(BaseModel):
    retrieved_count: int
    top_score: float | None
    score_margin: float | None
    duplicate_ratio: float

    signals: dict[str, bool]
    retrieval_outcome: Literal[
        "not_required",
        "not_attempted",
        "no_results",
        "results",
        "unknown",
    ] = "unknown"
    latency_anomaly: bool = False
    slow_stage: str | None = None
    slow_stage_latency_ms: float | None = None

    status: Literal[
        "HEALTHY",
        "DEGRADED",
        "FAILURE",
    ]
