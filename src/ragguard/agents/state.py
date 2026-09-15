from dataclasses import dataclass, field
from ragguard.auth.tenant_context import TenantContext

@dataclass
class RAGGuardState:
    query: str
    context: TenantContext | None = None
    retrieval_result: object | None = None
    evaluation_result: object | None = None
    failure_event: object | None = None
    diagnosis: object | None = None
    repair_plan: object | None = None
    repair_result: object | None = None
    validation_result: object | None = None
    status: str = "started"
    attempted_repairs: list = field(default_factory=list)
