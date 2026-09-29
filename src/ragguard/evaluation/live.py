from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RetrievedChunkObservation(BaseModel):
    id: str
    score: float


class ObservationSource(BaseModel):
    application_id: str
    environment: str


class RAGObservation(BaseModel):
    """Application-neutral snapshot of one RAG retrieval and answer."""

    contract_version: Literal["v1"]
    source: ObservationSource
    query: str
    retrieved_chunks: list[RetrievedChunkObservation] = Field(default_factory=list)
    retrieval_method: str = "unknown"
    embedding_degraded: bool = False
    retrieval_latency_ms: float = 0.0
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

    status: Literal[
        "HEALTHY",
        "DEGRADED",
        "FAILURE",
    ]
