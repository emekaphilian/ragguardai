from time import perf_counter

from sklearn.feature_extraction.text import TfidfVectorizer

from ragguard.common.schemas import RetrievalResult
from ragguard.common.enums import RetrievalMethod
from ragguard.auth.tenant_context import ApplicationScope


class VectorStore:
    """Offline implementation of a replaceable vector-store contract."""

    def __init__(self):
        self.chunks = []
        self.vectorizers = {}
        self.matrices = {}
        self.namespace_indexes = {}
        self.scope_vectorizers = {}
        self.scope_matrices = {}
        self.scope_indexes = {}
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
        self.scope_vectorizers.clear()
        self.scope_matrices.clear()
        self.scope_indexes.clear()
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
        scopes = {
            (
                chunk.metadata.get("tenant_namespace", "development"),
                chunk.metadata.get("ragguard_tenant_id"),
                chunk.metadata.get("application_id"),
                chunk.metadata.get("environment"),
            )
            for chunk in self.chunks
            if chunk.metadata.get("ragguard_tenant_id") is not None
            and chunk.metadata.get("application_id") is not None
            and chunk.metadata.get("environment") is not None
        }
        for scope in scopes:
            owned_indexes = [
                index for index, chunk in enumerate(self.chunks)
                if (
                    chunk.metadata.get("tenant_namespace", "development"),
                    chunk.metadata.get("ragguard_tenant_id"),
                    chunk.metadata.get("application_id"),
                    chunk.metadata.get("environment"),
                ) == scope
            ]
            owned = [self.chunks[index] for index in owned_indexes]
            vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
            try:
                matrix = vectorizer.fit_transform([chunk.text for chunk in owned])
            except ValueError:
                continue
            self.scope_vectorizers[scope] = vectorizer
            self.scope_matrices[scope] = matrix
            self.scope_indexes[scope] = owned_indexes
        if len(self.vectorizers) == 1:
            self.vectorizer, self.matrix = next(iter(self.vectorizers.values())), next(iter(self.matrices.values()))
        else:
            self.matrix = None

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        scope: ApplicationScope,
    ) -> RetrievalResult:
        if not isinstance(scope, ApplicationScope):
            raise ValueError("Application retrieval requires a complete ApplicationScope.")
        key = (
            scope.vector_namespace,
            scope.tenant_id,
            scope.application_id,
            scope.environment,
        )
        return self._search(
            query,
            top_k,
            indexes=self.scope_indexes.get(key, []),
            vectorizer=self.scope_vectorizers.get(key),
            matrix=self.scope_matrices.get(key),
        )

    def search_privileged(
        self,
        query: str,
        top_k: int = 5,
        *,
        namespace: str,
    ) -> RetrievalResult:
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("Privileged retrieval requires an explicit namespace.")
        return self._search(
            query,
            top_k,
            indexes=self.namespace_indexes.get(namespace, []),
            vectorizer=self.vectorizers.get(namespace),
            matrix=self.matrices.get(namespace),
        )

    def _search(self, query, top_k, *, indexes, vectorizer, matrix):
        start = perf_counter()
        if not indexes or matrix is None or vectorizer is None:
            return RetrievalResult(
                query=query,
                documents=[],
                scores=[],
                retrieval_method=RetrievalMethod.VECTOR
            )

        # Each matrix and vocabulary is fitted only from this namespace's chunks.
        q = vectorizer.transform([query])
        scores = (matrix @ q.T).toarray().ravel()

        ranked_local = sorted(range(len(indexes)), key=lambda index: scores[index], reverse=True)[:top_k]
        order = [indexes[index] for index in ranked_local]

        return RetrievalResult(
            query=query,
            documents=[self.chunks[i] for i in order],
            scores=[float(scores[i]) for i in ranked_local],
            retrieval_method=RetrievalMethod.VECTOR,
            latency_ms=(perf_counter() - start) * 1000,
        )
