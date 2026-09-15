from ragguard.retrieval.hybrid import hybrid_retrieve

def run_hybrid(store, query, top_k=5):
    return hybrid_retrieve(store, query, top_k)
