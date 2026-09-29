import re

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
    result = []
    section_title = ""
    ignored_heading_level: int | None = None
    paragraph_lines: list[str] = []
    section_paragraphs: list[str] = []

    def emit_chunk(paragraphs: list[str]) -> None:
        if not paragraphs:
            return
        body = "\n".join(paragraphs).strip()
        heading = f"{section_title}\n" if section_title else ""
        text = f"{heading}{body}".strip()
        metadata = {**document.metadata}
        if section_title:
            metadata["section_title"] = section_title
        result.append(Chunk(
            chunk_id=f"{document.document_id}-{len(result)}",
            document_id=document.document_id,
            text=text,
            metadata=metadata,
        ))

    def flush_paragraph() -> None:
        nonlocal section_paragraphs
        paragraph = " ".join(line.strip() for line in paragraph_lines).strip()
        paragraph_lines.clear()
        if not paragraph:
            return
        # Keep oversized paragraphs bounded without splitting decimal numbers.
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", paragraph)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            candidate = " ".join(section_paragraphs + [sentence])
            prefix_length = len(section_title) + 1 if section_title else 0
            if section_paragraphs and len(candidate) + prefix_length > max_chars:
                emit_chunk(section_paragraphs)
                section_paragraphs = []
            if len(sentence) + prefix_length > max_chars:
                emit_chunk(section_paragraphs)
                section_paragraphs = []
                for start in range(0, len(sentence), max_chars):
                    emit_chunk([sentence[start:start + max_chars]])
            else:
                section_paragraphs.append(sentence)

    for line in document.text.splitlines():
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if ignored_heading_level is not None:
                if level > ignored_heading_level:
                    continue
                ignored_heading_level = None
            if re.search(r"\btest questions?\b|^expected RAGGuard dashboard behavior$", title, re.IGNORECASE):
                flush_paragraph()
                emit_chunk(section_paragraphs)
                section_paragraphs = []
                ignored_heading_level = level
                continue
            flush_paragraph()
            emit_chunk(section_paragraphs)
            section_paragraphs = []
            section_title = title
        elif ignored_heading_level is not None:
            continue
        elif not line.strip():
            flush_paragraph()
        else:
            paragraph_lines.append(line)

    flush_paragraph()
    emit_chunk(section_paragraphs)
    return result
