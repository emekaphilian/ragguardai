from ragguard.retrieval.reranker import lexical_rerank

def rerank(query, retrieval):
    retrieval.documents = lexical_rerank(query, retrieval.documents)
    return retrieval
