from ragguard.common.exceptions import RetrievalError
from ragguard.auth.tenant_context import TenantContext
from ragguard.retrieval.hybrid import hybrid_retrieve, keyword_retrieve
from ragguard.retrieval.vector import vector_retrieve


def retrieve(store, query, method="vector", top_k=5, *, context: TenantContext):
    if not query or not query.strip():
        raise RetrievalError("Retrieval query must not be empty.")

    if top_k < 1:
        raise RetrievalError("top_k must be greater than zero.")

    if not isinstance(context, TenantContext):
        raise RetrievalError("Retrieval requires a complete tenant and application context.")
    scope = context.scope

    try:
        if method in {"hybrid", "keyword"}:
            original_store = store

            from types import SimpleNamespace

            store = SimpleNamespace(
                chunks=[
                    chunk
                    for chunk in original_store.chunks
                    if (
                        chunk.metadata.get("tenant_namespace"),
                        chunk.metadata.get("ragguard_tenant_id"),
                        chunk.metadata.get("application_id"),
                        chunk.metadata.get("environment"),
                    )
                    == (
                        scope.vector_namespace,
                        scope.tenant_id,
                        scope.application_id,
                        scope.environment,
                    )
                ],
                search=lambda q, k: original_store.search(
                    q,
                    k,
                    scope=scope,
                ),
            )

        if method == "hybrid":
            return hybrid_retrieve(store, query, top_k)

        if method == "keyword":
            return keyword_retrieve(store.chunks, query, top_k)

        if method != "vector":
            raise RetrievalError(
                f"Unsupported retrieval method: {method}"
            )

        return vector_retrieve(store, query, top_k, scope=scope)

    except RetrievalError:
        raise

    except Exception as exc:
        raise RetrievalError("Retrieval failed.") from exc


def retrieve_privileged(store, query, method="vector", top_k=5, *, namespace: str):
    """Run an explicitly privileged retrieval within one vector namespace."""
    if not query or not query.strip():
        raise RetrievalError("Retrieval query must not be empty.")
    if top_k < 1:
        raise RetrievalError("top_k must be greater than zero.")
    if not isinstance(namespace, str) or not namespace.strip():
        raise RetrievalError("Privileged retrieval requires an explicit namespace.")

    try:
        if method in {"hybrid", "keyword"}:
            from types import SimpleNamespace

            original_store = store
            store = SimpleNamespace(
                chunks=[
                    chunk for chunk in original_store.chunks
                    if chunk.metadata.get("tenant_namespace") == namespace
                ],
                search=lambda q, k: original_store.search_privileged(
                    q, k, namespace=namespace
                ),
            )
        if method == "hybrid":
            return hybrid_retrieve(store, query, top_k)
        if method == "keyword":
            return keyword_retrieve(store.chunks, query, top_k)
        if method != "vector":
            raise RetrievalError(f"Unsupported retrieval method: {method}")
        return store.search_privileged(query, top_k, namespace=namespace)
    except RetrievalError:
        raise
    except Exception as exc:
        raise RetrievalError("Privileged retrieval failed.") from exc
