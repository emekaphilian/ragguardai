from pydantic import BaseModel, Field

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
    metrics: dict

class RepairRequest(BaseModel):
    repair_type: str
    query: str
