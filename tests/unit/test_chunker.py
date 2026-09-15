from ragguard.common.schemas import Document
from ragguard.ingestion.chunker import sentence_aware

def test_sentence_chunking():
    chunks = sentence_aware(
        Document(document_id="x", text="One sentence. Two sentence."),
        100,
    )
    assert len(chunks) == 1
    assert "One sentence." in chunks[0].text
