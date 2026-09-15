from ragguard.common.schemas import Document
from ragguard.ingestion.chunker import sentence_aware
from ragguard.storage.vector_store import VectorStore

def test_retrieval_pipeline():
    doc = Document(document_id="d", text="Refunds are available in 30 days.")
    store = VectorStore()
    store.add(sentence_aware(doc, 100))
    assert store.search("refund 30 days", 1).documents
