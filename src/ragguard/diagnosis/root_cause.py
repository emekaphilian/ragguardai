from ragguard.common.enums import FailureMode, RepairType

POLICY = {
    FailureMode.LOW_CONTEXT_RECALL: [RepairType.HYBRID_RETRIEVAL, RepairType.RECHUNK],
    FailureMode.LOW_CONTEXT_PRECISION: [RepairType.RERANK, RepairType.DEDUPLICATE],
    FailureMode.LOW_FAITHFULNESS: [RepairType.HYBRID_RETRIEVAL, RepairType.CITATION_VALIDATION],
    FailureMode.LOW_ANSWER_RELEVANCY: [RepairType.QUERY_DECOMPOSITION, RepairType.HYBRID_RETRIEVAL],
    FailureMode.STALE_INDEX: [RepairType.REINDEX],
    FailureMode.POOR_CHUNKING: [RepairType.RECHUNK],
    FailureMode.DUPLICATE_CONTEXT: [RepairType.DEDUPLICATE],
    FailureMode.MULTI_HOP_FAILURE: [RepairType.QUERY_DECOMPOSITION],
}

def recommended_repairs(mode):
    return POLICY.get(mode, [RepairType.HUMAN_ESCALATION])
