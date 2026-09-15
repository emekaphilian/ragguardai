from ragguard.common.schemas import Document
from .chunker import fixed_width, sentence_aware

def process_document(document: Document, strategy: str = "sentence", **kwargs):
    if strategy == "fixed":
        return fixed_width(document, **kwargs)
    return sentence_aware(document, **kwargs)
