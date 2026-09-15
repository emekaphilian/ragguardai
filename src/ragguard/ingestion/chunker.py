from ragguard.common.schemas import Document, Chunk

def fixed_width(document: Document, size: int = 500, overlap: int = 50) -> list[Chunk]:
    if size <= overlap:
        raise ValueError("size must be greater than overlap")
    result = []
    step = size - overlap
    for i, start in enumerate(range(0, len(document.text), step)):
        text = document.text[start:start + size].strip()
        if text:
            result.append(Chunk(
                chunk_id=f"{document.document_id}-{i}",
                document_id=document.document_id,
                text=text,
                metadata=document.metadata,
            ))
    return result

def sentence_aware(document: Document, max_chars: int = 500) -> list[Chunk]:
    sentences = [s.strip() for s in document.text.replace("\n", " ").split(".") if s.strip()]
    result, current, length = [], [], 0
    for sentence in sentences:
        piece = sentence + "."
        if current and length + len(piece) > max_chars:
            i = len(result)
            result.append(Chunk(
                chunk_id=f"{document.document_id}-{i}",
                document_id=document.document_id,
                text=" ".join(current),
                metadata=document.metadata,
            ))
            current, length = [], 0
        current.append(piece)
        length += len(piece) + 1
    if current:
        i = len(result)
        result.append(Chunk(
            chunk_id=f"{document.document_id}-{i}",
            document_id=document.document_id,
            text=" ".join(current),
            metadata=document.metadata,
        ))
    return result
