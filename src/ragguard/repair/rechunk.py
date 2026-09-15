from ragguard.ingestion.chunker import sentence_aware

def rechunk(document, max_chars=500):
    return sentence_aware(document, max_chars=max_chars)
