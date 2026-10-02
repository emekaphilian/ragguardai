from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ragguard.common.schemas import EvaluationResult
from ragguard.config import MAX_REPAIR_ATTEMPTS
from ragguard.detection.live_failure import LiveFailureEvent
from ragguard.evaluation.live import LiveEvaluation

class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = 5
    method: str = "hybrid"
    record_run: bool = True
    application_id: str | None = None
    environment: str | None = None

class QueryResponse(BaseModel):
    answer: str
    rag_status: str
    retrieval_quality: dict
    sources: list[dict] = []
    retrieval_method: str = "hybrid"
    latency_ms: float = 0.0
    reliability_evaluation: LiveEvaluation | None = None
    reliability_failure: LiveFailureEvent | None = None
    application_id: str | None = None
    environment: str | None = None
    knowledge_source: str | None = None


class AdapterRetrievedChunk(BaseModel):
    id: str = Field(min_length=1)
    score: float
    text: str = ""
    document_id: str | None = None
    source: str | None = None
    section: str | None = None


class ExternalRAGQueryResponse(BaseModel):
    contract_version: Literal["v1"]
    answer: str
    retrieved_chunks: list[AdapterRetrievedChunk] = Field(default_factory=list)
    retrieval_method: str
    retrieval_latency_ms: float = Field(default=0.0, ge=0)
    embedding_degraded: bool = False

class DocumentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)


class ApplicationRegistrationRequest(BaseModel):
    ragguard_tenant_id: str = Field(min_length=1, max_length=100)
    application_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    display_name: str = Field(min_length=1, max_length=160)
    environment: str = Field(min_length=1, max_length=80)
    knowledge_source: Literal[
        "managed_index",
        "external_rag_api",
        "observation_only",
    ]
    vector_namespace: str | None = None
    query_endpoint_url: str | None = None
    query_token_env_var: str | None = Field(default=None, max_length=128)
    observation_token_env_var: str = Field(min_length=2, max_length=128)
    active: bool = True

class EvaluateRequest(BaseModel):
    query: str
    answer: str
    relevant_chunk_ids: list[str] = []

class DetectRequest(BaseModel):
    query: str
    metrics: EvaluationResult

class RepairRequest(BaseModel):
    query: str
    answer: str = Field(min_length=1)
    relevant_chunk_ids: list[str] = Field(min_length=1)
    top_k: int = Field(default=5, ge=1)
    application_id: str | None = None
    environment: str | None = None
    max_repair_attempts: int | None = Field(
        default=None,
        ge=0,
        le=MAX_REPAIR_ATTEMPTS,
    )


class RecoveryAttemptResponse(BaseModel):
    strategy: str
    status: str
    improvement: float | None = None


class RecoveryResultResponse(BaseModel):
    status: str
    recovery_id: str | None = None
    graph_run_id: str | None = None
    failure_detected: bool = False
    failure_type: str | None = None
    attempts: list[RecoveryAttemptResponse] = Field(default_factory=list)
    original_score: float | None = None
    final_score: float | None = None
    improvement: float | None = None
    completed_nodes: list[str] = Field(default_factory=list)
    escalation_reason: str | None = None
    repair_capability: Literal["available", "unavailable"] | None = None
    repair_authorization: Literal["authorized", "not_authorized"] | None = None
    repair_attempted: bool = False
    authorization_source: str | None = None
    authorization_reason: str | None = None


class ObservationRecoveryResponse(BaseModel):
    status: str
    evaluation: LiveEvaluation
    failure: LiveFailureEvent | None = None
    recovery: RecoveryResultResponse | None = None


class RecoveryAuditEventResponse(BaseModel):
    event_id: str
    recovery_id: str
    event_type: str
    timestamp: datetime
    failure_id: str | None = None
    graph_run_id: str | None = None
    application_id: str | None = None
    environment: str | None = None
    tenant_id: str | None = None
    ragguard_tenant_id: str | None = None
    attempt: int | None = None
    strategy: str | None = None
    status: str | None = None
    before_score: float | None = None
    after_score: float | None = None
    improvement: float | None = None
    validation_valid: bool | None = None
    validation_improved: bool | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecoveryAuditResponse(BaseModel):
    recovery_id: str
    graph_run_id: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    failure_id: str | None = None
    failure_type: str | None = None
    application_id: str | None = None
    environment: str | None = None
    tenant_id: str | None = None
    ragguard_tenant_id: str | None = None
    final_status: str
    original_score: float | None = None
    final_score: float | None = None
    improvement: float | None = None
    repair_capability: str | None = None
    repair_authorization: str | None = None
    repair_attempted: bool = False
    authorization_source: str | None = None
    authorization_reason: str | None = None
    query: str | None = None
    retrieval_method: str | None = None
    embedding_degraded: bool | None = None
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    events: list[RecoveryAuditEventResponse] = Field(default_factory=list)


class RecoveryAuditPageResponse(BaseModel):
    items: list[RecoveryAuditResponse] = Field(default_factory=list)
    page: int
    page_size: int
    total: int
    has_next: bool
