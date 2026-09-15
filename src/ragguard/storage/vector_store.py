from time import perf_counter
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from ragguard.common.schemas import RetrievalResult
from ragguard.common.enums import RetrievalMethod

class VectorStore:
    """Offline implementation of a replaceable vector-store contract."""

    def __init__(self):
        self.chunks = []
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        self.matrix = None

    def add(self, chunks, namespace: str | None = None):
        if namespace is not None:
            for chunk in chunks:
                chunk.metadata = {**chunk.metadata, "tenant_namespace": namespace}
        self.chunks.extend(chunks)
        self.matrix = self.vectorizer.fit_transform([c.text for c in self.chunks])

    def search(self, query, top_k=5, namespace: str | None = None):
        start = perf_counter()
        candidate_indexes = [index for index, chunk in enumerate(self.chunks) if namespace is None or chunk.metadata.get("tenant_namespace") == namespace]
        if not candidate_indexes:
            return RetrievalResult(
                query=query, documents=[], scores=[],
                retrieval_method=RetrievalMethod.VECTOR
            )
        # The matrix is fitted over all chunks, so calculate scores only after
        # selecting the namespace-owned positions.
        q = self.vectorizer.transform([query])
        scores = (self.matrix @ q.T).toarray().ravel()
        order = sorted(candidate_indexes, key=lambda index: scores[index], reverse=True)[:top_k]
        return RetrievalResult(
            query=query,
            documents=[self.chunks[i] for i in order],
            scores=[float(scores[i]) for i in order],
            retrieval_method=RetrievalMethod.VECTOR,
            latency_ms=(perf_counter() - start) * 1000,
        )
