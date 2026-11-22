from time import perf_counter

from sklearn.feature_extraction.text import TfidfVectorizer

from ragguard.common.schemas import RetrievalResult
from ragguard.common.enums import RetrievalMethod


class VectorStore:
    """Offline implementation of a replaceable vector-store contract."""

    def __init__(self):
        self.chunks = []
        self.vectorizers = {}
        self.matrices = {}
        self.namespace_indexes = {}
        # Legacy properties remain useful to callers inspecting a single-namespace store.
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        self.matrix = None

    def add(self, chunks, namespace: str | None = None):
        if namespace is not None:
            for chunk in chunks:
                chunk.metadata = {
                    **chunk.metadata,
                    "tenant_namespace": namespace,
                }

        self.chunks.extend(chunks)

        namespaces = {chunk.metadata.get("tenant_namespace", "development") for chunk in self.chunks}
        self.vectorizers.clear()
        self.matrices.clear()
        self.namespace_indexes.clear()
        for current_namespace in namespaces:
            owned_indexes = [index for index, chunk in enumerate(self.chunks) if chunk.metadata.get("tenant_namespace", "development") == current_namespace]
            owned = [self.chunks[index] for index in owned_indexes]
            vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
            try:
                self.matrices[current_namespace] = vectorizer.fit_transform([chunk.text for chunk in owned])
            except ValueError:
                continue
            self.vectorizers[current_namespace] = vectorizer
            self.namespace_indexes[current_namespace] = owned_indexes
        if len(self.vectorizers) == 1:
            self.vectorizer, self.matrix = next(iter(self.vectorizers.values())), next(iter(self.matrices.values()))
        else:
            self.matrix = None

    def search(self, query, top_k=5, namespace: str | None = None):
        start = perf_counter()

        selected_namespace = namespace
        if selected_namespace is None:
            namespaces = {chunk.metadata.get("tenant_namespace", "development") for chunk in self.chunks}
            if len(namespaces) == 1:
                selected_namespace = next(iter(namespaces))
        candidate_indexes = self.namespace_indexes.get(selected_namespace, [])
        vectorizer = self.vectorizers.get(selected_namespace)
        matrix = self.matrices.get(selected_namespace)
        if not candidate_indexes or matrix is None or vectorizer is None:
            return RetrievalResult(
                query=query,
                documents=[],
                scores=[],
                retrieval_method=RetrievalMethod.VECTOR
            )

        # Each matrix and vocabulary is fitted only from this namespace's chunks.
        q = vectorizer.transform([query])
        scores = (matrix @ q.T).toarray().ravel()

        ranked_local = [
            i for i in sorted(range(len(candidate_indexes)), key=lambda index: scores[index], reverse=True)
            if scores[i] > 0.0
        ][:top_k]
        order = [candidate_indexes[index] for index in ranked_local]

        return RetrievalResult(
            query=query,
            documents=[self.chunks[i] for i in order],
            scores=[float(scores[i]) for i in ranked_local],
            retrieval_method=RetrievalMethod.VECTOR,
            latency_ms=(perf_counter() - start) * 1000,
        )
