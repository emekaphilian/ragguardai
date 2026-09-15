from .vector import vector_retrieve
from .hybrid import hybrid_retrieve, keyword_retrieve

def retrieve(store, query, method="vector", top_k=5, context=None):
    namespace = context.vector_namespace if context is not None else None
    # Hybrid and keyword adapters currently operate on an in-memory list.
    # Give them only the authenticated tenant's chunks.
    if namespace is not None and method in {"hybrid", "keyword"}:
        original_store = store
        from types import SimpleNamespace
        store = SimpleNamespace(
            chunks=[chunk for chunk in original_store.chunks if chunk.metadata.get("tenant_namespace") == namespace],
            search=lambda q, k: original_store.search(q, k, namespace=namespace),
        )
    if method == "hybrid":
        return hybrid_retrieve(store, query, top_k)
    if method == "keyword":
        return keyword_retrieve(store.chunks, query, top_k)
    return store.search(query, top_k, namespace=namespace) if namespace is not None else vector_retrieve(store, query, top_k)
