def reindex(store, chunks):
    store.chunks = []
    store.matrix = None
    store.add(chunks)
    return store
