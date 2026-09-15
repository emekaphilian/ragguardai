from ragguard.common.schemas import Document
from ragguard.ingestion.chunker import sentence_aware
from ragguard.storage.vector_store import VectorStore

def test_ingest_index():
    chunks = sentence_aware(
        Document(document_id="d", text="Refunds are available in 30 days."),
        100,
    )
    store = VectorStore()
    store.add(chunks)
    assert len(store.chunks) == 1
