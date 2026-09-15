from ragguard.common.schemas import Document
from ragguard.ingestion.chunker import sentence_aware
from ragguard.storage.vector_store import VectorStore

def test_quality_has_signal():
    store = VectorStore()
    store.add(sentence_aware(
        Document(document_id="d", text="Refunds are available within 30 days."),
        100,
    ))
    result = store.search("refund 30 days", 1)
    assert result.scores[0] > 0
