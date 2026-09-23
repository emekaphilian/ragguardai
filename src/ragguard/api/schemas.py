from pydantic import BaseModel, Field

from ragguard.common.schemas import EvaluationResult

class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = 5
    method: str = "hybrid"

class QueryResponse(BaseModel):
    answer: str
    rag_status: str
    retrieval_quality: dict
    sources: list[dict] = []
    retrieval_method: str = "hybrid"
    latency_ms: float = 0.0

class DocumentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)

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
