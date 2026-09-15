def lexical_rerank(query, documents):
    query_terms = set(query.lower().split())
    return sorted(
        documents,
        key=lambda d: len(query_terms & set(d.text.lower().split())),
        reverse=True,
    )
