import re
from ragguard.common.schemas import RetrievalResult
from ragguard.common.enums import RetrievalMethod

def _tokens(text):
    return set(re.findall(r"\b\w+\b", text.lower()))

def keyword_retrieve(chunks, query, top_k=5):
    q = _tokens(query)
    scored = []
    for chunk in chunks:
        overlap = len(q & _tokens(chunk.text))
        score = overlap / max(1, len(q))
        scored.append((score, chunk))
    scored.sort(key=lambda item: -item[0])
    chosen = scored[:top_k]
    return RetrievalResult(
        query=query,
        documents=[c for _, c in chosen],
        scores=[float(s) for s, _ in chosen],
        retrieval_method=RetrievalMethod.KEYWORD,
    )

def hybrid_retrieve(store, query, top_k=5, alpha=0.5):
    vector = store.search(query, max(top_k * 2, 10))
    keyword = keyword_retrieve(store.chunks, query, max(top_k * 2, 10))
    fused = {}
    for rank, chunk in enumerate(vector.documents):
        fused[chunk.chunk_id] = fused.get(chunk.chunk_id, 0) + alpha / (rank + 1)
    for rank, chunk in enumerate(keyword.documents):
        fused[chunk.chunk_id] = fused.get(chunk.chunk_id, 0) + (1 - alpha) / (rank + 1)
    by_id = {c.chunk_id: c for c in store.chunks}
    ranked = sorted(fused.items(), key=lambda item: -item[1])[:top_k]
    return RetrievalResult(
        query=query,
        documents=[by_id[k] for k, _ in ranked],
        scores=[float(v) for _, v in ranked],
        retrieval_method=RetrievalMethod.HYBRID,
    )
