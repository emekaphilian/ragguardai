from ragguard.auth.tenant_context import ApplicationScope


def vector_retrieve(store, query, top_k=5, *, scope: ApplicationScope):
    return store.search(query, top_k, scope=scope)
