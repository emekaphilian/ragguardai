from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field
from .enums import RetrievalMethod, FailureMode, Severity, RepairType

class Document(BaseModel):
    document_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)

class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)

class RetrievalResult(BaseModel):
    query: str
    documents: list[Chunk]
    scores: list[float]
    retrieval_method: RetrievalMethod
    latency_ms: float = 0.0

class EvaluationResult(BaseModel):
    context_precision: float
    context_recall: float
    faithfulness: float
    answer_relevancy: float
    citation_accuracy: float = 1.0
    overall_score: float

class FailureEvent(BaseModel):
    failure_id: str
    query: str
    failure_type: FailureMode
    severity: Severity
    metrics: EvaluationResult
    evidence: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class DiagnosisResult(BaseModel):
    failure_id: str
    root_cause: FailureMode
    confidence: float
    evidence: list[str] = Field(default_factory=list)
    recommended_repairs: list[RepairType] = Field(default_factory=list)

class RepairResult(BaseModel):
    repair_id: str
    failure_id: str
    repair_type: RepairType
    before_metrics: EvaluationResult
    after_metrics: EvaluationResult
    improvement: float
    status: str
    rollback_available: bool = True

class ValidationResult(BaseModel):
    valid: bool
    improved: bool
    score_delta: float
    message: str
