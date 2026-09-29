from dataclasses import dataclass, field

from ragguard.auth.tenant_context import TenantContext
from ragguard.observability.recovery_audit import RecoveryAuditRecord


@dataclass
class RAGGuardState:
    query: str
    context: TenantContext | None = None
    observation: object | None = None

    retrieval_result: object | None = None
    evaluation_result: object | None = None

    original_retrieval: object | None = None
    original_metrics: object | None = None
    candidate_retrieval: object | None = None
    candidate_metrics: object | None = None

    failure_event: object | None = None
    diagnosis: object | None = None

    repair_plan: object | None = None
    repair_result: object | None = None
    validation_result: object | None = None

    attempted_repairs: list = field(default_factory=list)
    repair_attempts: list[dict] = field(default_factory=list)

    status: str = "started"
    escalation_reason: str | None = None
    completed_nodes: list[str] = field(default_factory=list)
    recovery_id: str | None = None
    graph_run_id: str | None = None
    recovery_audit: RecoveryAuditRecord | None = None
