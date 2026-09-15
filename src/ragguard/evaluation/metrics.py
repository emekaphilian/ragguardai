from ragguard.common.schemas import EvaluationResult

def _clip(value):
    return max(0.0, min(1.0, float(value)))

def context_precision(retrieval, relevant_ids):
    if not retrieval.documents:
        return 0.0
    return _clip(sum(c.chunk_id in relevant_ids for c in retrieval.documents) / len(retrieval.documents))

def context_recall(retrieval, relevant_ids):
    if not relevant_ids:
        return 1.0
    found = {c.chunk_id for c in retrieval.documents}
    return _clip(len(found & relevant_ids) / len(relevant_ids))

def answer_relevancy(query, answer):
    q, a = set(query.lower().split()), set(answer.lower().split())
    return _clip(len(q & a) / max(1, len(q)))

def faithfulness(answer, retrieval):
    if not answer:
        return 0.0
    context = " ".join(c.text.lower() for c in retrieval.documents)
    terms = [t for t in answer.lower().split() if len(t) > 3]
    return _clip(sum(t in context for t in terms) / max(1, len(terms)))

def evaluate(query, answer, retrieval, relevant_ids):
    cp = context_precision(retrieval, relevant_ids)
    cr = context_recall(retrieval, relevant_ids)
    f = faithfulness(answer, retrieval)
    ar = answer_relevancy(query, answer)
    citation = cp
    overall = (cp + cr + f + ar + citation) / 5
    return EvaluationResult(
        context_precision=cp,
        context_recall=cr,
        faithfulness=f,
        answer_relevancy=ar,
        citation_accuracy=citation,
        overall_score=overall,
    )
