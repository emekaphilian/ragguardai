# Failure Modes

The domain explicitly models low context precision, low context recall, low faithfulness, low answer relevancy, stale indexes, poor chunking, duplicate context, cross-document entity collapse, single-hop blindness, multi-hop failure, reranking failure, embedding mismatch, citation failure and context fragmentation.

The detector uses deterministic thresholds and a priority order. This prevents arbitrary LLM-generated classifications from becoming the system control plane.
