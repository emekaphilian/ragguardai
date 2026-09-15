from ragguard.common.schemas import Chunk, RetrievalResult
from ragguard.common.enums import RetrievalMethod
from ragguard.evaluation.metrics import context_precision, context_recall

def test_precision_recall():
    result = RetrievalResult(
        query="q",
        documents=[Chunk(chunk_id="a", document_id="d", text="x")],
        scores=[1],
        retrieval_method=RetrievalMethod.VECTOR,
    )
    assert context_precision(result, {"a"}) == 1
    assert context_recall(result, {"a"}) == 1
