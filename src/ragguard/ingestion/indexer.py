from ragguard.storage.vector_store import VectorStore

def index_chunks(store: VectorStore, chunks):
    store.add(chunks)
