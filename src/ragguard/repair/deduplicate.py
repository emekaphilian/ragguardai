from __future__ import annotations

from ragguard.common.schemas import RetrievalResult


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def retrieval_stats(retrieval: RetrievalResult) -> dict[str, int]:
    """Return observable duplicate counts for a retrieval result."""
    total = len(retrieval.documents)
    unique = len({_normalize_text(document.text) for document in retrieval.documents})
    return {
        "retrieved_chunks": total,
        "unique_chunks": unique,
        "duplicate_chunks": total - unique,
    }


def deduplicate(retrieval: RetrievalResult, top_k: int | None = None) -> RetrievalResult:
    """Remove repeated chunks while keeping the highest-scoring copy of each text."""
    unique: dict[str, tuple[object, float]] = {}

    for document, score in zip(retrieval.documents, retrieval.scores):
        key = _normalize_text(document.text)
        if key not in unique:
            unique[key] = (document, score)
        elif score > unique[key][1]:
            unique[key] = (document, score)

    ranked = sorted(unique.values(), key=lambda item: item[1], reverse=True)
    if top_k is not None:
        ranked = ranked[:top_k]
    deduped_documents = [doc for doc, _ in ranked]
    deduped_scores = [float(score) for _, score in ranked]

    return RetrievalResult(
        query=retrieval.query,
        documents=deduped_documents,
        scores=deduped_scores,
        retrieval_method=retrieval.retrieval_method,
        latency_ms=retrieval.latency_ms,
    )
