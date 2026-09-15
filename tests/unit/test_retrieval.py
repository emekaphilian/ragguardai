from ragguard.common.schemas import Chunk
from ragguard.storage.vector_store import VectorStore

def test_vector_retrieval():
    store = VectorStore()
    store.add([
        Chunk(chunk_id="a", document_id="d", text="refund within thirty days"),
        Chunk(chunk_id="b", document_id="d", text="security incident within twenty four hours"),
    ])
    result = store.search("refund thirty days", 1)
    assert result.documents[0].chunk_id == "a"
