def vector_retrieve(store, query, top_k=5):
    return store.search(query, top_k)
