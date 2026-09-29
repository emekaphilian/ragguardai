import re
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from ragguard.common.schemas import RetrievalResult
from ragguard.common.enums import RetrievalMethod


def _tokens(text):
    tokens = set(re.findall(r"\b\w+\b", text.lower())) - ENGLISH_STOP_WORDS - {"minimum", "length"}
    normalized = set()
    for token in tokens:
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
            token = token[:-1]
        normalized.add(token)
    return normalized

def keyword_retrieve(chunks, query, top_k=5):
    q = _tokens(query)
    if not q:
        return RetrievalResult(query=query, documents=[], scores=[], retrieval_method=RetrievalMethod.KEYWORD)
    scored = []

    for chunk in chunks:
        overlap = len(q & _tokens(chunk.text))
        score = overlap / max(1, len(q))
        if overlap >= min(2, len(q)):
            scored.append((score, chunk))

    scored.sort(key=lambda item: -item[0])
    chosen = scored[:top_k]

    return RetrievalResult(
        query=query,
        documents=[chunk for _, chunk in chosen],
        scores=[float(score) for score, _ in chosen],
        retrieval_method=RetrievalMethod.KEYWORD,
    )

def hybrid_retrieve(store, query, top_k=5, alpha=0.5):
    if not _tokens(query):
        return RetrievalResult(query=query, documents=[], scores=[], retrieval_method=RetrievalMethod.HYBRID)
    vector = store.search(query, max(top_k * 2, 10))
    keyword = keyword_retrieve(
        store.chunks,
        query,
        max(top_k * 2, 10),
    )

    fused = {}

    for rank, (chunk, score) in enumerate(zip(vector.documents, vector.scores)):
        if score <= 0:
            continue
        fused[chunk.chunk_id] = (
            fused.get(chunk.chunk_id, 0.0)
            + alpha / (rank + 1)
        )

    for rank, chunk in enumerate(keyword.documents):
        fused[chunk.chunk_id] = (
            fused.get(chunk.chunk_id, 0.0)
            + (1.0 - alpha) / (rank + 1)
        )

    by_id = {chunk.chunk_id: chunk for chunk in store.chunks}

    query_tokens = _tokens(query)
    relevance = {
        chunk.chunk_id: len(query_tokens & _tokens(chunk.text)) / max(1, len(query_tokens))
        for chunk in store.chunks
    }
    minimum_overlap = min(2, len(query_tokens))
    minimum_relevance = minimum_overlap / max(1, len(query_tokens))

    ranked = sorted(
        fused.items(),
        key=lambda item: -item[1],
    )
    ranked = [item for item in ranked if relevance[item[0]] >= minimum_relevance][:top_k]

    # Reciprocal-rank fusion is a ranking score, not a confidence value.
    # Return a lexical relevance score so telemetry remains bounded and useful.
    return RetrievalResult(
        query=query,
        documents=[by_id[chunk_id] for chunk_id, _ in ranked],
        scores=[float(relevance[chunk_id]) for chunk_id, _ in ranked],
        retrieval_method=RetrievalMethod.HYBRID,
    )
