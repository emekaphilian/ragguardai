from ragguard.observability.observation_activity import ObservationRecord


def observation_run(record: ObservationRecord) -> dict:
    observation = record.observation
    evaluation = record.evaluation
    failure = record.failure or {}
    recovery = record.recovery or {}
    return {
        "id": record.observation_id,
        "query": record.query,
        "status": record.status,
        "method": observation.get("retrieval_method", "unknown"),
        "latency_ms": observation.get("retrieval_latency_ms", 0),
        "created_at": record.created_at.isoformat(),
        "quality": {},
        "tenant_id": record.ragguard_tenant_id,
        "source": "observation",
        "application_id": record.application_id,
        "environment": observation.get("source", {}).get("environment"),
        "retrieved_count": evaluation.get("retrieved_count", 0),
        "top_score": evaluation.get("top_score"),
        "score_margin": evaluation.get("score_margin"),
        "embedding_degraded": observation.get("embedding_degraded", False),
        "failure_type": failure.get("failure_type"),
        "recovery_status": recovery.get("status"),
    }


def observation_failure(record: ObservationRecord) -> dict:
    failure = record.failure or {}
    recovery_status = (record.recovery or {}).get("status")
    status = (
        "resolved" if recovery_status == "promoted"
        else "escalated" if recovery_status == "escalated"
        else "open"
    )
    return {
        "id": failure.get("failure_id", record.observation_id),
        "type": failure.get("failure_type", "UNKNOWN"),
        "severity": failure.get("severity", "unknown"),
        "query": record.query,
        "status": status,
        "evidence": failure.get("evidence", []),
        "created_at": record.created_at.isoformat(),
        "tenant_id": record.ragguard_tenant_id,
        "application_id": record.application_id,
        "environment": record.observation.get("source", {}).get("environment"),
    }