# Repair Strategies

| Failure | Preferred repair |
|---|---|
| Poor chunking | Re-chunk |
| Stale index | Re-index |
| Low recall | Hybrid retrieval |
| Poor ranking | Reranker |
| Duplicate context | Deduplication |
| Citation failure | Citation validation |
| Multi-hop failure | Query decomposition |
| Persistent failure | Human escalation |

The repair policy is a safety boundary:

Detection → Diagnosis → Approved Repair → Execution → Validation
